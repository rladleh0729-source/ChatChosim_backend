from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Header, HTTPException
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

app = FastAPI(
    title="ChatChosim Backend",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# 기본 유틸
# =========================

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_data_files() -> None:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

    for file_path in [PENDING_FILE, APPROVED_FILE, REJECTED_FILE]:
        path = Path(file_path)
        if not path.exists():
            path.write_text("[]", encoding="utf-8")


def load_json_list(file_path: Path | str) -> List[Dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def save_json_list(file_path: Path | str, data: List[Dict[str, Any]]) -> None:
    path = Path(file_path)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def require_admin_token(x_admin_token: Optional[str]) -> None:
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="관리자 인증에 실패했다.")


def send_resend_email(to_email: str, subject: str, html: str) -> Dict[str, Any]:
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY가 설정되지 않았다.")
    if not RESEND_FROM_EMAIL:
        raise RuntimeError("RESEND_FROM_EMAIL이 설정되지 않았다.")

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=20)

    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    if response.status_code >= 400:
        raise RuntimeError(f"Resend 메일 전송 실패: {data}")

    return data


def send_admin_notification(submission: Dict[str, Any]) -> Dict[str, Any]:
    if not ADMIN_NOTIFY_EMAIL:
        raise RuntimeError("ADMIN_NOTIFY_EMAIL이 설정되지 않았다.")

    subject = f"[ChatChosim] 새 데이터 제안 도착 - {submission['title']}"
    html = f"""
    <div style="font-family:Arial, sans-serif; line-height:1.7; color:#111827;">
      <h2 style="margin-bottom:16px;">새 데이터 제안이 도착했습니다.</h2>

      <p><strong>이름:</strong> {submission['name']}</p>
      <p><strong>이메일:</strong> {submission['email']}</p>
      <p><strong>분류:</strong> {submission['category']}</p>
      <p><strong>제목:</strong> {submission['title']}</p>
      <p><strong>ID:</strong> {submission['id']}</p>
      <p><strong>상태:</strong> {submission['status']}</p>
      <p><strong>제출 시각:</strong> {submission['created_at']}</p>

      <div style="margin-top:18px; padding:14px; background:#f8fafc; border-radius:10px;">
        <strong>내용</strong><br>
        <div style="white-space:pre-wrap;">{submission['content']}</div>
      </div>
    </div>
    """
    return send_resend_email(ADMIN_NOTIFY_EMAIL, subject, html)


def send_feedback_email(submission: Dict[str, Any], feedback_message: str) -> Dict[str, Any]:
    subject = f"[ChatChosim] 제안 검토 피드백 - {submission['title']}"
    html = f"""
    <div style="font-family:Arial, sans-serif; line-height:1.7; color:#111827;">
      <h2 style="margin-bottom:16px;">보내주신 제안에 대한 피드백입니다.</h2>

      <p><strong>이름:</strong> {submission['name']}</p>
      <p><strong>제목:</strong> {submission['title']}</p>
      <p><strong>제안 ID:</strong> {submission['id']}</p>

      <div style="margin-top:18px; padding:14px; background:#eff6ff; border-radius:10px;">
        <strong>관리자 피드백</strong><br>
        <div style="white-space:pre-wrap;">{feedback_message}</div>
      </div>

      <div style="margin-top:18px; padding:14px; background:#f8fafc; border-radius:10px;">
        <strong>기존 제안 내용</strong><br>
        <div style="white-space:pre-wrap;">{submission['content']}</div>
      </div>
    </div>
    """
    return send_resend_email(submission["email"], subject, html)


def send_approved_email(submission: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    subject = f"[ChatChosim] 제안 수락 안내 - {submission['title']}"
    extra = f"<p><strong>추가 안내:</strong> {note}</p>" if note.strip() else ""
    html = f"""
    <div style="font-family:Arial, sans-serif; line-height:1.7; color:#111827;">
      <h2 style="margin-bottom:16px;">보내주신 제안이 수락되었습니다.</h2>

      <p><strong>이름:</strong> {submission['name']}</p>
      <p><strong>제목:</strong> {submission['title']}</p>
      <p><strong>제안 ID:</strong> {submission['id']}</p>
      {extra}

      <div style="margin-top:18px; padding:14px; background:#ecfdf5; border-radius:10px;">
        보내주신 제안을 검토한 뒤 반영 대상으로 수락했습니다.
      </div>
    </div>
    """
    return send_resend_email(submission["email"], subject, html)


def send_rejected_email(submission: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    subject = f"[ChatChosim] 제안 검토 결과 - {submission['title']}"
    extra = f"<p><strong>안내:</strong> {reason}</p>" if reason.strip() else ""
    html = f"""
    <div style="font-family:Arial, sans-serif; line-height:1.7; color:#111827;">
      <h2 style="margin-bottom:16px;">보내주신 제안 검토 결과입니다.</h2>

      <p><strong>이름:</strong> {submission['name']}</p>
      <p><strong>제목:</strong> {submission['title']}</p>
      <p><strong>제안 ID:</strong> {submission['id']}</p>
      {extra}

      <div style="margin-top:18px; padding:14px; background:#fff7ed; border-radius:10px;">
        이번에는 반영 대상으로 선정되지 않았습니다. 그래도 제안해 주셔서 감사합니다.
      </div>
    </div>
    """
    return send_resend_email(submission["email"], subject, html)


def build_submission(
    name: str,
    email: str,
    category: str,
    title: str,
    content: str,
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "email": email.strip(),
        "category": category.strip(),
        "title": title.strip(),
        "content": content.strip(),
        "status": "pending",
        "feedback_history": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def get_pending_items() -> List[Dict[str, Any]]:
    return load_json_list(PENDING_FILE)


def get_approved_items() -> List[Dict[str, Any]]:
    return load_json_list(APPROVED_FILE)


def get_rejected_items() -> List[Dict[str, Any]]:
    return load_json_list(REJECTED_FILE)


def save_pending_items(items: List[Dict[str, Any]]) -> None:
    save_json_list(PENDING_FILE, items)


def save_approved_items(items: List[Dict[str, Any]]) -> None:
    save_json_list(APPROVED_FILE, items)


def save_rejected_items(items: List[Dict[str, Any]]) -> None:
    save_json_list(REJECTED_FILE, items)


def find_submission_by_id(submission_id: str) -> Optional[Dict[str, Any]]:
    for item in get_pending_items():
        if item.get("id") == submission_id:
            return item

    for item in get_approved_items():
        if item.get("id") == submission_id:
            return item

    for item in get_rejected_items():
        if item.get("id") == submission_id:
            return item

    return None


def move_pending_to_approved(submission_id: str) -> Dict[str, Any]:
    pending_items = get_pending_items()
    approved_items = get_approved_items()

    target = None
    remained = []

    for item in pending_items:
        if item.get("id") == submission_id:
            target = item
        else:
            remained.append(item)

    if not target:
        raise HTTPException(status_code=404, detail="대상 제안을 찾지 못했다.")

    target["status"] = "approved"
    target["updated_at"] = now_iso()

    approved_items.append(target)
    save_pending_items(remained)
    save_approved_items(approved_items)

    return target


def move_pending_to_rejected(submission_id: str) -> Dict[str, Any]:
    pending_items = get_pending_items()
    rejected_items = get_rejected_items()

    target = None
    remained = []

    for item in pending_items:
        if item.get("id") == submission_id:
            target = item
        else:
            remained.append(item)

    if not target:
        raise HTTPException(status_code=404, detail="대상 제안을 찾지 못했다.")

    target["status"] = "rejected"
    target["updated_at"] = now_iso()

    rejected_items.append(target)
    save_pending_items(remained)
    save_rejected_items(rejected_items)

    return target


# =========================
# 요청/응답 모델
# =========================

class SubmissionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    category: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=5000)


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class ApproveRequest(BaseModel):
    note: str = ""


class RejectRequest(BaseModel):
    reason: str = ""


class FeedbackRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=3000)


# =========================
# 기본 라우트
# =========================

@app.on_event("startup")
def startup_event() -> None:
    ensure_data_files()


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "message": "ChatChosim backend is running"
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok"
    }


# =========================
# 사용자 제출 API
# =========================

@app.post("/api/submit-data")
def submit_data(payload: SubmissionCreate) -> Dict[str, Any]:
    submission = build_submission(
        name=payload.name,
        email=payload.email,
        category=payload.category,
        title=payload.title,
        content=payload.content,
    )

    pending_items = get_pending_items()
    pending_items.append(submission)
    save_pending_items(pending_items)

    mail_error = None
    try:
        send_admin_notification(submission)
    except Exception as e:
        mail_error = str(e)

    response = {
        "message": "제안이 저장되었고 관리자 이메일로 알림을 보냈습니다." if mail_error is None else "제안은 저장되었지만 관리자 알림 메일 전송은 실패했습니다.",
        "id": submission["id"],
    }

    if mail_error:
        response["mail_error"] = mail_error

    return response


# =========================
# 관리자 인증
# =========================

@app.post("/api/admin/login")
def admin_login(payload: AdminLoginRequest) -> Dict[str, Any]:
    if payload.username != ADMIN_USERNAME or payload.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="관리자 로그인에 실패했다.")

    return {
        "message": "관리자 로그인에 성공했다.",
        "token": ADMIN_TOKEN,
    }


# =========================
# 관리자 조회 API
# =========================

@app.get("/api/admin/submissions")
def get_all_submissions(
    x_admin_token: Optional[str] = Header(default=None),
    status: Optional[str] = None,
) -> Dict[str, Any]:
    require_admin_token(x_admin_token)

    pending_items = get_pending_items()
    approved_items = get_approved_items()
    rejected_items = get_rejected_items()

    all_items = pending_items + approved_items + rejected_items

    all_items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    if status:
      all_items = [item for item in all_items if item.get("status") == status]

    return {
        "count": len(all_items),
        "items": all_items,
    }


@app.get("/api/admin/submissions/{submission_id}")
def get_submission_detail(
    submission_id: str,
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_admin_token(x_admin_token)

    target = find_submission_by_id(submission_id)
    if not target:
        raise HTTPException(status_code=404, detail="해당 제안을 찾지 못했다.")

    return target


# =========================
# 관리자 처리 API
# =========================

@app.post("/api/admin/submissions/{submission_id}/approve")
def approve_submission(
    submission_id: str,
    payload: ApproveRequest,
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_admin_token(x_admin_token)

    updated = move_pending_to_approved(submission_id)

    email_error = None
    try:
        send_approved_email(updated, payload.note)
    except Exception as e:
        email_error = str(e)

    return {
        "message": "제안을 수락 처리했다." if email_error is None else "제안은 수락 처리했지만 수락 안내 메일 전송은 실패했다.",
        "item": updated,
        "email_error": email_error,
    }


@app.post("/api/admin/submissions/{submission_id}/reject")
def reject_submission(
    submission_id: str,
    payload: RejectRequest,
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_admin_token(x_admin_token)

    updated = move_pending_to_rejected(submission_id)

    email_error = None
    try:
        send_rejected_email(updated, payload.reason)
    except Exception as e:
        email_error = str(e)

    return {
        "message": "제안을 거절 처리했다." if email_error is None else "제안은 거절 처리했지만 거절 안내 메일 전송은 실패했다.",
        "item": updated,
        "email_error": email_error,
    }


@app.post("/api/admin/submissions/{submission_id}/feedback")
def send_feedback(
    submission_id: str,
    payload: FeedbackRequest,
    x_admin_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    require_admin_token(x_admin_token)

    pending_items = get_pending_items()
    target = None

    for item in pending_items:
        if item.get("id") == submission_id:
            target = item
            break

    if not target:
        raise HTTPException(status_code=404, detail="피드백 대상 제안을 찾지 못했다. pending 상태 제안만 피드백을 보낼 수 있다.")

    target["status"] = "feedback_sent"
    target["updated_at"] = now_iso()
    target.setdefault("feedback_history", []).append(
        {
            "message": payload.message,
            "sent_at": now_iso(),
        }
    )
    save_pending_items(pending_items)

    email_error = None
    try:
        send_feedback_email(target, payload.message)
    except Exception as e:
        email_error = str(e)

    return {
        "message": "피드백을 전송했다." if email_error is None else "피드백 상태는 저장했지만 메일 전송은 실패했다.",
        "item": target,
        "email_error": email_error,
    }
