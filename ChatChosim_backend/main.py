from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone
import json
import uuid

import resend
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from config import (
    DATA_DIR,
    PENDING_FILE,
    APPROVED_FILE,
    REJECTED_FILE,
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
    ADMIN_TOKEN,
    ALLOWED_ORIGINS,
    RESEND_API_KEY,
    RESEND_FROM_EMAIL,
    ADMIN_NOTIFY_EMAIL,
)

app = FastAPI(title="ChatChosim Backend", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubmissionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    category: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=10000)


class ReviewRequest(BaseModel):
    review_note: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


def ensure_file(path: Path) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def initialize_storage() -> None:
    ensure_file(PENDING_FILE)
    ensure_file(APPROVED_FILE)
    ensure_file(REJECTED_FILE)


def read_json(path: Path) -> List[dict]:
    ensure_file(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        path.write_text("[]", encoding="utf-8")
        return []


def write_json(path: Path, data: List[dict]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_admin_email(subject: str, body: str) -> None:
    if not RESEND_API_KEY or "여기에_Resend_API_Key" in RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY가 설정되지 않았습니다.")

    resend.api_key = RESEND_API_KEY

    params = {
        "from": f"ChatChosim <{RESEND_FROM_EMAIL}>",
        "to": [ADMIN_NOTIFY_EMAIL],
        "subject": subject,
        "html": f"""
        <div style="font-family:Arial, sans-serif; line-height:1.7; color:#1f2937;">
          <h2 style="margin-bottom:12px;">새 데이터 제안이 도착했습니다.</h2>
          <pre style="white-space:pre-wrap; background:#f8fafc; padding:12px; border-radius:8px;">{body}</pre>
        </div>
        """
    }

    resend.Emails.send(params)


def require_admin_token(authorization: Optional[str]) -> None:
    expected = f"Bearer {ADMIN_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="관리자 인증 실패")


@app.on_event("startup")
def startup_event() -> None:
    initialize_storage()


@app.get("/")
def root():
    return {"message": "ChatChosim Backend is running"}


@app.post("/api/admin/login")
def admin_login(payload: LoginRequest):
    if payload.username != ADMIN_USERNAME or payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    return {
        "message": "로그인 성공",
        "token": ADMIN_TOKEN
    }


@app.post("/api/submit-data")
def submit_data(payload: SubmissionCreate):
    pending = read_json(PENDING_FILE)

    record = {
        "id": str(uuid.uuid4()),
        "name": payload.name.strip(),
        "email": payload.email,
        "category": payload.category.strip(),
        "title": payload.title.strip(),
        "content": payload.content.strip(),
        "submitted_at": now_iso(),
        "status": "pending",
        "reviewed_at": None,
        "reviewer": None,
        "review_note": None,
    }

    pending.append(record)
    write_json(PENDING_FILE, pending)

    mail_subject = f"[ChatChosim] 새 데이터 제안 도착 - {record['title']}"
    mail_body = f"""새 데이터 제안이 도착했습니다.

이름: {record['name']}
이메일: {record['email']}
분류: {record['category']}
제목: {record['title']}
ID: {record['id']}

내용:
{record['content']}

제출 시각:
{record['submitted_at']}
"""

    try:
        send_admin_email(mail_subject, mail_body)
    except Exception as e:
        return {
            "message": "제출은 저장되었지만 이메일 발송은 실패했습니다.",
            "id": record["id"],
            "email_error": str(e)
        }

    return {
        "message": "제안이 저장되었고 관리자 이메일로 알림을 보냈습니다.",
        "id": record["id"]
    }


@app.get("/api/admin/pending")
def get_pending(authorization: Optional[str] = Header(default=None)):
    require_admin_token(authorization)
    return read_json(PENDING_FILE)


@app.get("/api/admin/approved")
def get_approved(authorization: Optional[str] = Header(default=None)):
    require_admin_token(authorization)
    return read_json(APPROVED_FILE)


@app.get("/api/admin/rejected")
def get_rejected(authorization: Optional[str] = Header(default=None)):
    require_admin_token(authorization)
    return read_json(REJECTED_FILE)


@app.post("/api/admin/approve/{item_id}")
def approve_item(item_id: str, payload: ReviewRequest, authorization: Optional[str] = Header(default=None)):
    require_admin_token(authorization)

    pending = read_json(PENDING_FILE)
    approved = read_json(APPROVED_FILE)

    target = None
    remain = []

    for item in pending:
        if item["id"] == item_id:
            target = item
        else:
            remain.append(item)

    if target is None:
        raise HTTPException(status_code=404, detail="대기 데이터에서 찾을 수 없습니다.")

    target["status"] = "approved"
    target["reviewed_at"] = now_iso()
    target["reviewer"] = ADMIN_USERNAME
    target["review_note"] = payload.review_note

    approved.append(target)

    write_json(PENDING_FILE, remain)
    write_json(APPROVED_FILE, approved)

    return {"message": "승인 완료", "id": item_id}


@app.post("/api/admin/reject/{item_id}")
def reject_item(item_id: str, payload: ReviewRequest, authorization: Optional[str] = Header(default=None)):
    require_admin_token(authorization)

    pending = read_json(PENDING_FILE)
    rejected = read_json(REJECTED_FILE)

    target = None
    remain = []

    for item in pending:
        if item["id"] == item_id:
            target = item
        else:
            remain.append(item)

    if target is None:
        raise HTTPException(status_code=404, detail="대기 데이터에서 찾을 수 없습니다.")

    target["status"] = "rejected"
    target["reviewed_at"] = now_iso()
    target["reviewer"] = ADMIN_USERNAME
    target["review_note"] = payload.review_note

    rejected.append(target)

    write_json(PENDING_FILE, remain)
    write_json(REJECTED_FILE, rejected)

    return {"message": "거절 완료", "id": item_id}