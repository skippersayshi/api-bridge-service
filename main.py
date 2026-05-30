import os, json, uuid, sqlite3, re
from datetime import datetime
from contextlib import asynccontextmanager
import anthropic, httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

DB = os.environ.get("DB_PATH", "bridges.db")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PORT = int(os.environ.get("PORT", 8000))

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            target_url TEXT,
            source_payload TEXT,
            transformed_payload TEXT,
            response_status INTEGER,
            response_body TEXT,
            status TEXT,
            error TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="API Bridge Service", lifespan=lifespan)

def get_client():
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

class BridgeRequest(BaseModel):
    source_payload: dict
    target_url: str
    mapping_instructions: str = ""
    target_headers: dict = {}

def extract_json(text: str) -> dict:
    text = re.sub(r'```(?:json)?\n?', '', text).strip('`').strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return {}

@app.post("/api/bridge")
async def bridge(req: BridgeRequest):
    exec_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    ai = get_client()

    conn = sqlite3.connect(DB)
    conn.execute(
        "INSERT INTO executions VALUES (?,?,?,?,?,?,?,?,?)",
        (exec_id, req.target_url, json.dumps(req.source_payload), None, None, None, "processing", None, created_at)
    )
    conn.commit()
    conn.close()

    try:
        instructions = req.mapping_instructions or "Map the source fields to appropriate target fields"
        transform_prompt = f"""Transform this source payload to match what the target API expects.

Source payload:
{json.dumps(req.source_payload, indent=2)}

Target URL: {req.target_url}
Mapping instructions: {instructions}

Return ONLY a valid JSON object with the transformed payload. No explanation."""

        transform_resp = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": transform_prompt}]
        )

        transformed = extract_json(transform_resp.content[0].text)

        headers = {"Content-Type": "application/json", **req.target_headers}
        async with httpx.AsyncClient(timeout=30) as http:
            fwd = await http.post(req.target_url, json=transformed, headers=headers)
            response_status = fwd.status_code
            try:
                response_body = fwd.json()
            except Exception:
                response_body = {"text": fwd.text[:500]}

        conn = sqlite3.connect(DB)
        conn.execute(
            "UPDATE executions SET transformed_payload=?, response_status=?, response_body=?, status='completed' WHERE id=?",
            (json.dumps(transformed), response_status, json.dumps(response_body), exec_id)
        )
        conn.commit()
        conn.close()

        return {
            "id": exec_id,
            "status": "completed",
            "transformed_payload": transformed,
            "response_status": response_status,
            "response_body": response_body
        }

    except Exception as e:
        conn = sqlite3.connect(DB)
        conn.execute("UPDATE executions SET status='failed', error=? WHERE id=?", (str(e), exec_id))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/executions")
async def get_executions(limit: int = 20):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, target_url, response_status, status, created_at FROM executions ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"id": r[0], "target_url": r[1], "response_status": r[2], "status": r[3], "created_at": r[4]} for r in rows]

@app.get("/api/stats")
async def get_stats():
    conn = sqlite3.connect(DB)
    total = conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
    completed = conn.execute("SELECT COUNT(*) FROM executions WHERE status='completed'").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM executions WHERE status='failed'").fetchone()[0]
    today = conn.execute("SELECT COUNT(*) FROM executions WHERE date(created_at)=date('now')").fetchone()[0]
    conn.close()
    success_rate = round((completed / total * 100) if total > 0 else 0, 1)
    return {"total": total, "completed": completed, "failed": failed, "today": today, "success_rate": success_rate}

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("index.html") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
