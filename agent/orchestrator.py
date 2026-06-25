import os
import sys
import json
import uuid
import logging
import asyncio
import argparse
from pathlib import Path
from typing import TypedDict, List, Dict, Any

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

from common.config import settings
from common.responses import ResponseFormat
from common.logging_setup import setup_logging
from agent.clients import make_client, make_llm
from agent.audited import audited_invoke

logger = logging.getLogger(__name__)


class PipelineState(TypedDict, total=False):
    input_path: str
    raw_text: str
    key_points: List[str]
    memory_ids: List[int]
    summary: str
    run_id: str
    report: Dict[str, Any]
    errors: List[str]


def parse_text(res: Any) -> str:
    """Extracts raw text content from a tool execution response.

    Handles both plain strings and MCP content-block lists
    ([{"type": "text", "text": "..."}]) that langchain-mcp-adapters may return.
    """
    content = getattr(res, "content", res)
    # Unwrap MCP content-block lists to the first text block
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                content = block.get("text", "")
                break
            elif isinstance(block, str):
                content = block
                break
        else:
            return ""
    if isinstance(content, str):
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "text" in data:
                return data["text"]
        except Exception:
            pass
        return content
    return str(content)


def parse_points(content: str) -> List[str]:
    """Helper to parse a list of key points from JSON response content, with fallback parser."""
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        data = json.loads(content)
        if isinstance(data, list):
            return [str(x) for x in data]
        elif isinstance(data, dict):
            for k in ["points", "key_points", "results"]:
                if k in data and isinstance(data[k], list):
                    return [str(x) for x in data[k]]
    except Exception:
        pass

    lines = []
    for line in content.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if line:
            lines.append(line)
    return lines


def parse_memory_id(res: Any) -> int | None:
    """Parses memory id from the memory_add JSON output."""
    content = parse_text(res)
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "id" in data:
            return int(data["id"])
    except Exception:
        pass
    return None


async def build_graph(llm: Any, tools: List[Any]) -> Any:
    """Compiles the deterministic LangGraph pipeline topology."""
    by_name = {t.name: t for t in tools}
    g = StateGraph(PipelineState)

    async def ingest_node(state: PipelineState) -> Dict[str, Any]:
        logger.info("[Node: Ingest] Validating input document path...")
        path = state.get("input_path", "")
        if not path or not os.path.exists(path):
            err_msg = f"Input path does not exist: '{path}'"
            logger.error(err_msg)
            return {"errors": state.get("errors", []) + [err_msg]}
        return {}

    async def convert_node(state: PipelineState) -> Dict[str, Any]:
        logger.info("[Node: Convert] Extracting text content using file bridge...")
        if state.get("errors"):
            return {}

        path = state["input_path"]
        src_path = Path(path).resolve()
        files_dir = Path(settings().files_dir).resolve()

        relative_path = path
        if not str(src_path).startswith(str(files_dir)):
            try:
                dest_path = files_dir / src_path.name
                files_dir.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(src_path.read_bytes())
                relative_path = src_path.name
                logger.info("Copied input file to files_dir sandbox: %s", dest_path)
            except Exception as e:
                err_msg = f"Failed sandbox copy: {e}"
                logger.error(err_msg)
                return {"errors": state.get("errors", []) + [err_msg]}
        else:
            relative_path = str(src_path.relative_to(files_dir))

        try:
            res = await by_name["filebridge_convert_file"].ainvoke({
                "source_path": relative_path,
                "to_format": "text"
            })
            raw_text = parse_text(res)

            try:
                data = json.loads(raw_text)
                if isinstance(data, dict) and data.get("isError"):
                    err_msg = data.get("error")
                    logger.error("File bridge returned error: %s", err_msg)
                    return {"errors": state.get("errors", []) + [err_msg]}
            except Exception:
                pass

            return {"raw_text": raw_text}
        except Exception as e:
            err_msg = f"Conversion step failed: {e}"
            logger.error(err_msg)
            return {"errors": state.get("errors", []) + [err_msg]}

    async def extract_node(state: PipelineState) -> Dict[str, Any]:
        logger.info("[Node: Extract] Extracting key facts via ChatOllama model...")
        if state.get("errors") or not state.get("raw_text"):
            return {}

        prompt = (
            "Extract the key facts, dates, and architectural decisions from the following text.\n"
            "Your output must be formatted as a valid JSON array of strings, where each string represents one key point.\n"
            "Do not include markdown json code fences (like ```json), introduction, or conversational filler.\n"
            "Output only the raw JSON array.\n\n"
            f"Text:\n{state['raw_text']}"
        )

        run_id = state["run_id"]
        messages = [HumanMessage(content=prompt)]

        try:
            resp = await audited_invoke(llm, by_name, run_id, "extract", messages, expect="json")
            points = parse_points(resp.content)

            if not points or len(points) == 0:
                logger.warning("JSON extraction returned empty result; retrying with stricter instructions...")
                correction_prompt = (
                    "You must output ONLY a valid JSON list of strings containing key points.\n"
                    "Do not add explanation. Here is the previous output that failed to parse:\n"
                    f"{resp.content}\n"
                    "Correct it now."
                )
                corr_messages = [HumanMessage(content=correction_prompt)]
                corr_resp = await audited_invoke(llm, by_name, run_id, "extract_retry", corr_messages, expect="json")
                points = parse_points(corr_resp.content)

            if not points:
                err_msg = "Extract node returned empty key points after retry."
                logger.error(err_msg)
                return {"errors": state.get("errors", []) + [err_msg], "key_points": []}

            logger.info("Extracted %d key points.", len(points))
            return {"key_points": points}
        except Exception as e:
            err_msg = f"Extraction step failed: {e}"
            logger.error(err_msg)
            return {"errors": state.get("errors", []) + [err_msg]}

    async def store_node(state: PipelineState) -> Dict[str, Any]:
        logger.info("[Node: Store] Storing facts in memory-server vector index...")
        if state.get("errors") or not state.get("key_points"):
            return {}

        memory_ids = []
        for p in state["key_points"]:
            try:
                res = await by_name["memory_add"].ainvoke({
                    "text": p,
                    "tags": ["extracted_fact"]
                })
                m_id = parse_memory_id(res)
                if m_id is not None:
                    memory_ids.append(m_id)
            except Exception as e:
                logger.warning("Failed to store fact '%s...': %s", p[:50], e)

        logger.info("Saved %d vectors in memory-server index.", len(memory_ids))
        return {"memory_ids": memory_ids}

    async def summarize_node(state: PipelineState) -> Dict[str, Any]:
        logger.info("[Node: Summarize] Generating context summary...")
        if state.get("errors") or not state.get("raw_text"):
            return {}

        prompt = (
            "Summarize the following text in a concise paragraph. "
            "Highlight the main takeaways, architectural components, and constraints.\n\n"
            f"Text:\n{state['raw_text']}"
        )

        run_id = state["run_id"]
        messages = [HumanMessage(content=prompt)]

        try:
            resp = await audited_invoke(llm, by_name, run_id, "summarize", messages, expect="text")
            return {"summary": resp.content}
        except Exception as e:
            err_msg = f"Summarization step failed: {e}"
            logger.error(err_msg)
            return {"errors": state.get("errors", []) + [err_msg]}

    async def report_node(state: PipelineState) -> Dict[str, Any]:
        logger.info("[Node: Report] Generating pipeline audit metrics report...")
        try:
            res = await by_name["audit_get_stats"].ainvoke({
                "run_id": state["run_id"],
                "response_format": "json"
            })
            report_data = json.loads(parse_text(res))
            return {"report": report_data}
        except Exception as e:
            logger.warning("Failed to load audit report stats: %s", e)
            return {}

    g.add_node("ingest", ingest_node)
    g.add_node("convert", convert_node)
    g.add_node("extract", extract_node)
    g.add_node("store", store_node)
    g.add_node("summarize", summarize_node)
    g.add_node("report", report_node)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "convert")
    g.add_edge("convert", "extract")
    g.add_edge("extract", "store")
    g.add_edge("store", "summarize")
    g.add_edge("summarize", "report")
    g.add_edge("report", END)

    return g.compile()


async def run_pipeline(input_file: str, react: bool = False):
    """Orchestrates pipeline execution using clients, llm, and graph compilation."""
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    logger.info("Initializing agent-mesh pipeline. Run ID: %s", run_id)

    client = make_client()
    try:
        tools = await client.get_tools()
        llm = make_llm()

        tool_names = [t.name for t in tools]
        logger.info("Connected to MCP servers. Loaded tools: %s", tool_names)

        if react:
            logger.info("Running in autonomous ReAct agent mode...")
            agent = create_react_agent(llm, tools)
            prompt = (
                f"Process the file at '{input_file}'. Follow these steps:\n"
                "1. Call filebridge_convert_file to convert it to plain text.\n"
                "2. Read the text and extract key points.\n"
                "3. For each key point, call memory_add to save it in memory.\n"
                "4. Summarize the text.\n"
                f"5. Call audit_get_stats with run_id='{run_id}' to compile the cost report."
            )
            logger.info("Executing ReAct agent invocation...")
            inputs = {"messages": [HumanMessage(content=prompt)]}
            res = await agent.ainvoke(inputs)
            messages = res.get("messages", [])
            if messages:
                logger.info("Final ReAct agent output received.")
                print(messages[-1].content)
            else:
                logger.warning("No output messages from ReAct agent.")
        else:
            logger.info("Running in deterministic pipeline mode...")
            graph = await build_graph(llm, tools)
            initial_state = {
                "input_path": input_file,
                "run_id": run_id,
                "errors": []
            }

            final_state = await graph.ainvoke(initial_state)

            errors = final_state.get("errors", [])
            if errors:
                logger.error("Pipeline completed with errors: %s", errors)

            print("\n==================================================")
            print("                  FINAL REPORT                    ")
            print("==================================================")
            print(f"Run ID: {final_state.get('run_id')}")
            print(f"Processed file: {final_state.get('input_path')}")
            print("\n--- Document Summary ---")
            print(final_state.get("summary", "No summary generated."))

            print("\n--- Extracted Facts Stored ---")
            m_ids = final_state.get("memory_ids", [])
            print(f"Stored {len(m_ids)} facts in vector index (IDs: {m_ids})")

            print("\n--- Cost & Audit Stats ---")
            report_data = final_state.get("report")
            if report_data:
                c = report_data.get("cost", {})
                lc = c.get("local", {})
                cc = c.get("notional_cloud", {})
                print(f"Local compute: {lc.get('compute_seconds', 0)} GPU seconds")
                print(f"Notional Cloud Cost: {cc.get('cost', 0):.4f} {cc.get('currency', 'USD')}")
                print(f"Total Call Count: {report_data.get('calls', 0)}")
                t = report_data.get("tokens", {})
                print(f"Tokens consumed: {t.get('total', 0)} (In: {t.get('in', 0)}, Out: {t.get('out', 0)})")
            else:
                print("No audit stats available.")
            print("==================================================")

    except Exception as e:
        logger.error("Pipeline execution aborted: %s", e)
        raise e


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="agent-mesh Orchestrator CLI")
    parser.add_argument("--input", default="examples/sample.md", help="Input file path to ingest")
    parser.add_argument("--react", action="store_true", help="Run autonomous ReAct agent instead of deterministic graph")
    args = parser.parse_args()

    setup_logging("orchestrator")
    asyncio.run(run_pipeline(args.input, args.react))
