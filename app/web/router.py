"""
Web Controller and Route Handlers for Koperasi Core.
Connects FastAPI views, Jinja2 templates, and domain services.
"""
from typing import Optional, List
from datetime import datetime
import secrets

from fastapi import APIRouter, Request, Response, Depends, Form, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response as RawResponse
from fastapi.templating import Jinja2Templates

from app.config import (
    SESSION_COOKIE_NAME,
    ROLE_SUPER_ADMIN,
    ROLE_ADMIN_KOPERASI,
    ROLE_ANGGOTA,
    ROLE_KETUA,
    ROLE_ATASAN_APPROVER,
    ROLE_BENDAHARA,
)
from app.auth.service import (
    authenticate_user,
    get_user_from_session,
    invalidate_session,
    create_password_reset_token,
    reset_password,
    accept_invitation,
    create_user_invitation,
    change_user_status,
    AuthenticationError,
)
from app.members.service import (
    list_members,
    get_member_by_id,
    create_member_manual,
    create_user_for_member,
    MemberAccessForbidden,
)
from app.bulk_import.engine import (
    generate_member_import_template,
    stage_and_preview_import,
    commit_import_batch,
    generate_error_report_csv,
    list_import_batches,
    get_import_batch_detail,
)
from app.savings.service import (
    get_member_savings_summary,
    get_account_transactions,
    record_opening_balance,
    record_deposit,
    generate_savings_opening_balance_template,
    SavingsError,
)
from app.loans.service import (
    apply_for_loan,
    process_approval,
    disburse_loan,
    pay_loan_installment,
    get_loan_details,
    calculate_loan_schedule,
    LoanError,
    MakerCheckerViolation,
)
from app.documents.service import verify_document_token, revoke_token
from app.reports.service import (
    get_role_dashboard_data,
    get_members_report,
    get_savings_ledger_report,
    get_financial_transactions_report,
    get_audit_trail_report,
)
from app.database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="koperasi_core/app/web/templates")

def get_current_user_optional(request: Request) -> Optional[dict]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return get_user_from_session(token)

def require_auth(request: Request) -> dict:
    user = get_current_user_optional(request)
    if not user:
        raise AuthenticationError("Silakan masuk terlebih dahulu.")
    return user

# Root Route
@router.get("/")
def index_view(request: Request):
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)

# Auth Views
@router.get("/login", response_class=HTMLResponse)
def login_view(request: Request, error: Optional[str] = None, success: Optional[str] = None):
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("auth/login.html", {
        "request": request, "current_user": None, "error": error, "success": success
    })

@router.post("/login")
def login_submit(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
):
    ip = request.client.host if request.client else "127.0.0.1"
    ua = request.headers.get("user-agent")
    try:
        session_data = authenticate_user(email=email, password=password, ip_address=ip, user_agent=ua)
        redirect = RedirectResponse(url="/dashboard", status_code=303)
        redirect.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_data["session_token"],
            httponly=True,
            samesite="lax",
        )
        return redirect
    except AuthenticationError as e:
        return templates.TemplateResponse("auth/login.html", {
            "request": request, "current_user": None, "error": str(e)
        })

@router.get("/logout")
def logout_view(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        invalidate_session(token)
    redirect = RedirectResponse(url="/login", status_code=303)
    redirect.delete_cookie(key=SESSION_COOKIE_NAME)
    return redirect

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_view(request: Request, error: Optional[str] = None, success: Optional[str] = None):
    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request, "current_user": None, "error": error, "success": success
    })

@router.post("/forgot-password")
def forgot_password_submit(request: Request, email: str = Form(...)):
    ip = request.client.host if request.client else "127.0.0.1"
    token = create_password_reset_token(email=email, ip_address=ip)
    # Notice: To not leak email existence to unauthorized callers, we show a general message.
    # For convenient local testing/demo, if token was generated, we provide the reset link in the message.
    if token:
        msg = f"Tautan reset berhasil dibuat: /reset-password?token={token}"
    else:
        msg = "Jika email terdaftar dan aktif, instruksi reset password telah diproses."
    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request, "current_user": None, "success": msg
    })

@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_view(request: Request, token: str = Query(...), error: Optional[str] = None):
    return templates.TemplateResponse("auth/reset_password.html", {
        "request": request, "current_user": None, "token": token, "error": error
    })

@router.post("/reset-password")
def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    if password != confirm_password:
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request, "current_user": None, "token": token, "error": "Konfirmasi password tidak cocok."
        })
    ip = request.client.host if request.client else "127.0.0.1"
    try:
        reset_password(token=token, new_password=password, ip_address=ip)
        return templates.TemplateResponse("auth/login.html", {
            "request": request, "current_user": None, "success": "Password berhasil diubah. Silakan masuk dengan password baru."
        })
    except Exception as e:
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request, "current_user": None, "token": token, "error": str(e)
        })

@router.get("/invite", response_class=HTMLResponse)
def invite_activation_view(request: Request, token: str = Query(...), error: Optional[str] = None):
    return templates.TemplateResponse("auth/invite.html", {
        "request": request, "current_user": None, "token": token, "error": error
    })

@router.post("/invite")
def invite_activation_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    if password != confirm_password:
        return templates.TemplateResponse("auth/invite.html", {
            "request": request, "current_user": None, "token": token, "error": "Konfirmasi password tidak cocok."
        })
    try:
        accept_invitation(token=token, new_password=password)
        return templates.TemplateResponse("auth/login.html", {
            "request": request, "current_user": None, "success": "Akun berhasil diaktivasi! Silakan login dengan password yang baru Anda buat."
        })
    except Exception as e:
        return templates.TemplateResponse("auth/invite.html", {
            "request": request, "current_user": None, "token": token, "error": str(e)
        })

# Dashboard View
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_view(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    metrics = get_role_dashboard_data(user)
    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "dashboard",
        **metrics,
    })

# Members Views
@router.get("/members", response_class=HTMLResponse)
def members_list_view(
    request: Request,
    q: Optional[str] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
    success: Optional[str] = None,
):
    user = require_auth(request)
    data = list_members(current_user=user, query=q, status=status)
    return templates.TemplateResponse("members/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "members",
        "members": data["items"],
        "total": data["total"],
        "query": q,
        "selected_status": status,
        "error": error,
        "success": success,
    })

@router.get("/members/new", response_class=HTMLResponse)
def members_new_view(request: Request):
    user = require_auth(request)
    return templates.TemplateResponse("members/new.html", {
        "request": request,
        "current_user": user,
        "active_tab": "members",
    })

@router.post("/members/new")
def members_new_submit(
    request: Request,
    member_number: str = Form(...),
    name: str = Form(...),
    nik: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    bank_account: Optional[str] = Form(None),
):
    user = require_auth(request)
    try:
        mem_id = create_member_manual({
            "member_number": member_number,
            "name": name,
            "nik": nik,
            "email": email,
            "phone": phone,
            "address": address,
            "bank_account": bank_account,
        }, user)
        return RedirectResponse(url=f"/members/{mem_id}?success=Anggota+berhasil+didaftarkan", status_code=303)
    except Exception as e:
        return templates.TemplateResponse("members/new.html", {
            "request": request, "current_user": user, "active_tab": "members", "error": str(e)
        })

@router.get("/members/{member_id}", response_class=HTMLResponse)
def member_detail_view(request: Request, member_id: int, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    try:
        member = get_member_by_id(member_id, user)
        savings = get_member_savings_summary(member_id, user)
        return templates.TemplateResponse("members/detail.html", {
            "request": request,
            "current_user": user,
            "active_tab": "members",
            "member": member,
            "savings": savings,
            "success": success,
            "error": error,
        })
    except Exception as e:
        return RedirectResponse(url=f"/members?error={str(e)}", status_code=303)

@router.post("/members/{member_id}/invite")
def member_invite_submit(request: Request, member_id: int):
    user = require_auth(request)
    try:
        inv = create_user_for_member(member_id, user)
        token = inv["invitation_token"]
        return RedirectResponse(url=f"/members/{member_id}?success=Undangan+aktivasi+akun+berhasil+dibuat.+Tautan:+/invite?token={token}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/members/{member_id}?error={str(e)}", status_code=303)

# Bulk Import Views
@router.get("/import", response_class=HTMLResponse)
def import_index_view(
    request: Request,
    batch_id: Optional[int] = None,
    error: Optional[str] = None,
    success: Optional[str] = None,
):
    user = require_auth(request)
    history = list_import_batches(limit=20)
    preview = None
    if batch_id:
        try:
            detail = get_import_batch_detail(batch_id)
            batch = detail["batch"]
            rows = detail["rows"]
            preview = {
                "batch_id": batch["id"],
                "batch_number": batch["batch_number"],
                "filename": batch["file_name"],
                "mode": batch["mode"],
                "dry_run": False,
                "summary": {
                    "total_rows": batch["total_rows"],
                    "valid_rows": batch["valid_rows"],
                    "invalid_rows": batch["invalid_rows"],
                    "warning_rows": batch["warning_count"],
                    "new_rows": batch["created_rows"],
                    "update_rows": batch["updated_rows"],
                    "duplicate_rows": 0,
                },
                "preview_rows": [
                    {
                        "row_number": r["row_number"],
                        "status": r["status"],
                        "action_type": r["action_type"],
                        "data": eval(r["normalized_data_json"]) if r["normalized_data_json"] else {},
                    }
                    for r in rows[:50]
                ],
                "all_errors": [],
                "can_commit": batch["status"] in ("VALIDATED", "PENDING_PREVIEW") and batch["invalid_rows"] == 0,
            }
        except Exception:
            pass

    return templates.TemplateResponse("import/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "import",
        "history": history,
        "preview": preview,
        "error": error,
        "success": success,
    })

@router.get("/import/template")
def download_import_template(format: str = Query("xlsx")):
    content, filename, mime_type = generate_member_import_template(file_format=format)
    return RawResponse(
        content=content,
        media_type=mime_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@router.post("/import/upload")
async def import_upload_submit(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("ADD_ONLY"),
    dry_run: Optional[str] = Form(None),
):
    user = require_auth(request)
    file_bytes = await file.read()
    is_dry = bool(dry_run)
    try:
        preview = stage_and_preview_import(
            file_bytes=file_bytes,
            filename=file.filename,
            mode=mode,
            current_user=user,
            dry_run=is_dry,
        )
        history = list_import_batches(limit=20)
        return templates.TemplateResponse("import/index.html", {
            "request": request,
            "current_user": user,
            "active_tab": "import",
            "history": history,
            "preview": preview,
            "success": f"File {file.filename} berhasil diproses & divalidasi.",
        })
    except Exception as e:
        history = list_import_batches(limit=20)
        return templates.TemplateResponse("import/index.html", {
            "request": request,
            "current_user": user,
            "active_tab": "import",
            "history": history,
            "preview": None,
            "error": str(e),
        })

@router.post("/import/commit/{batch_id}")
def import_commit_submit(request: Request, batch_id: int):
    user = require_auth(request)
    try:
        result = commit_import_batch(batch_id=batch_id, current_user=user)
        msg = f"Batch berhasil di-commit! Dibuat: {result['created_rows']}, Diperbarui: {result['updated_rows']}, Gagal: {result['failed_rows']}."
        return RedirectResponse(url=f"/import?success={msg}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/import?error={str(e)}", status_code=303)

@router.get("/import/batch/{batch_id}/errors")
def download_import_errors(batch_id: int):
    content, filename = generate_error_report_csv(batch_id)
    return RawResponse(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

# Savings Views
@router.get("/savings", response_class=HTMLResponse)
def savings_index_view(request: Request, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    # Default to user's member_id or first active member
    member_id = user.get("member_id")
    if not member_id:
        with get_db() as conn:
            m = conn.execute("SELECT id FROM members LIMIT 1").fetchone()
            member_id = m["id"] if m else 1

    savings = get_member_savings_summary(member_id, user)
    new_idemp = f"IDEMP-DEP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"

    return templates.TemplateResponse("savings/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "savings",
        "savings": savings,
        "new_idempotency_key": new_idemp,
        "success": success,
        "error": error,
    })

@router.get("/savings/account/{account_id}", response_class=HTMLResponse)
def savings_account_view(request: Request, account_id: int):
    user = require_auth(request)
    with get_db() as conn:
        acc = conn.execute("SELECT * FROM savings_accounts WHERE id = ?", (account_id,)).fetchone()
        if not acc:
            return RedirectResponse(url="/savings?error=Rekening+tidak+ditemukan", status_code=303)

    txs = get_account_transactions(account_id, user)
    return templates.TemplateResponse("savings/account.html", {
        "request": request,
        "current_user": user,
        "active_tab": "savings",
        "account": dict(acc),
        "transactions": txs,
    })

@router.post("/savings/deposit")
def savings_deposit_submit(
    request: Request,
    account_id: int = Form(...),
    amount: str = Form(...),
    description: Optional[str] = Form(None),
    idempotency_key: str = Form(...),
):
    user = require_auth(request)
    try:
        res = record_deposit(
            account_id=account_id,
            amount_str=amount,
            description=description or "",
            idempotency_key=idempotency_key,
            current_user=user,
        )
        return RedirectResponse(url="/savings?success=Setoran+simpanan+berhasil+dicatat+ke+buku+besar", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/savings?error={str(e)}", status_code=303)

@router.get("/savings/opening-balance", response_class=HTMLResponse)
def savings_opening_balance_view(request: Request, member_id: Optional[int] = None):
    user = require_auth(request)
    with get_db() as conn:
        members = conn.execute("SELECT id, member_number, name FROM members ORDER BY name ASC").fetchall()
    return templates.TemplateResponse("savings/opening_balance.html", {
        "request": request,
        "current_user": user,
        "active_tab": "savings",
        "members": [dict(m) for m in members],
        "selected_member_id": member_id,
        "today": datetime.utcnow().strftime("%Y-%m-%d"),
    })

@router.post("/savings/opening-balance")
def savings_opening_balance_submit(
    request: Request,
    member_id: int = Form(...),
    account_type: str = Form(...),
    amount: str = Form(...),
    effective_date: str = Form(...),
    reference: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    user = require_auth(request)
    try:
        record_opening_balance(
            member_id=member_id,
            account_type=account_type,
            amount_str=amount,
            effective_date=effective_date,
            reference=reference or "",
            notes=notes or "",
            current_user=user,
        )
        return RedirectResponse(url="/savings?success=Saldo+awal+berhasil+direkam+ke+ledger+simpanan", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/savings/opening-balance?error={str(e)}", status_code=303)

@router.get("/savings/opening-balance/template")
def download_ob_template(format: str = Query("xlsx")):
    content, filename, mime_type = generate_savings_opening_balance_template(file_format=format)
    return RawResponse(
        content=content,
        media_type=mime_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

# Loans Views
@router.get("/loans", response_class=HTMLResponse)
def loans_index_view(request: Request, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    member_id = user.get("member_id")
    is_staff = any(r in {ROLE_SUPER_ADMIN, ROLE_ADMIN_KOPERASI, ROLE_KETUA, ROLE_BENDAHARA, ROLE_ATASAN_APPROVER} for r in user["roles"])

    with get_db() as conn:
        if is_staff:
            active_loans = conn.execute(
                """
                SELECT l.*, m.name as member_name, m.member_number
                FROM loans l JOIN members m ON l.member_id = m.id
                ORDER BY l.id DESC
                """,
            ).fetchall()
            applications = conn.execute(
                """
                SELECT la.*, m.name as member_name, m.member_number
                FROM loan_applications la JOIN members m ON la.member_id = m.id
                ORDER BY la.id DESC
                """,
            ).fetchall()
        else:
            active_loans = conn.execute(
                """
                SELECT l.*, m.name as member_name, m.member_number
                FROM loans l JOIN members m ON l.member_id = m.id
                WHERE l.member_id = ?
                ORDER BY l.id DESC
                """,
                (member_id or 0,),
            ).fetchall()
            applications = conn.execute(
                """
                SELECT la.*, m.name as member_name, m.member_number
                FROM loan_applications la JOIN members m ON la.member_id = m.id
                WHERE la.member_id = ?
                ORDER BY la.id DESC
                """,
                (member_id or 0,),
            ).fetchall()

    return templates.TemplateResponse("loans/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "loans",
        "active_loans": [dict(l) for l in active_loans],
        "applications": [dict(a) for a in applications],
        "success": success,
        "error": error,
    })

@router.get("/loans/apply", response_class=HTMLResponse)
def loans_apply_view(request: Request):
    user = require_auth(request)
    with get_db() as conn:
        members = conn.execute("SELECT id, member_number, name FROM members WHERE membership_status = 'ACTIVE'").fetchall()
    return templates.TemplateResponse("loans/apply.html", {
        "request": request,
        "current_user": user,
        "active_tab": "loans",
        "members": [dict(m) for m in members],
    })

@router.post("/loans/apply")
def loans_apply_submit(
    request: Request,
    amount: str = Form(...),
    tenor_months: int = Form(...),
    purpose: str = Form(...),
    member_id: Optional[int] = Form(None),
):
    user = require_auth(request)
    target_member_id = member_id or user.get("member_id")
    if not target_member_id:
        return RedirectResponse(url="/loans/apply?error=Pilih+anggota+pemohon", status_code=303)

    try:
        app_res = apply_for_loan(
            member_id=target_member_id,
            amount_str=amount,
            tenor_months=tenor_months,
            purpose=purpose,
            current_user=user,
        )
        return RedirectResponse(url=f"/loans/application/{app_res['application_id']}?success=Pengajuan+pinjaman+berhasil+dikirim", status_code=303)
    except Exception as e:
        with get_db() as conn:
            members = conn.execute("SELECT id, member_number, name FROM members WHERE membership_status = 'ACTIVE'").fetchall()
        return templates.TemplateResponse("loans/apply.html", {
            "request": request, "current_user": user, "active_tab": "loans", "members": [dict(m) for m in members], "error": str(e)
        })

@router.get("/loans/application/{app_id}", response_class=HTMLResponse)
def loan_application_view(request: Request, app_id: int, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    with get_db() as conn:
        app_row = conn.execute("SELECT * FROM loan_applications WHERE id = ?", (app_id,)).fetchone()
        if not app_row:
            return RedirectResponse(url="/loans?error=Pengajuan+tidak+ditemukan", status_code=303)

        member = conn.execute(
            """
            SELECT m.*, d.name as department_name, p.title as position_title, e.manager_id
            FROM members m
            LEFT JOIN employees e ON m.employee_id = e.id
            LEFT JOIN departments d ON e.department_id = d.id
            LEFT JOIN positions p ON e.position_id = p.id
            WHERE m.id = ?
            """,
            (app_row["member_id"],),
        ).fetchone()

        mgr_name = None
        if member and member["manager_id"]:
            mgr_emp = conn.execute("SELECT name FROM employees WHERE id = ?", (member["manager_id"],)).fetchone()
            if mgr_emp:
                mgr_name = mgr_emp["name"]

        approvals_cur = conn.execute(
            """
            SELECT la.*, u.full_name as approver_name
            FROM loan_approvals la
            JOIN users u ON la.approver_id = u.id
            WHERE la.application_id = ?
            ORDER BY la.id ASC
            """,
            (app_id,),
        ).fetchall()

    is_own = (member["user_id"] == user["id"])
    can_appr = False
    if not is_own:
        if app_row["current_step"] == "MANAGER" and (ROLE_ATASAN_APPROVER in user["roles"] or ROLE_SUPER_ADMIN in user["roles"] or app_row["assigned_manager_id"] == user["id"]):
            can_appr = True
        elif app_row["current_step"] == "KETUA" and (ROLE_KETUA in user["roles"] or ROLE_SUPER_ADMIN in user["roles"]):
            can_appr = True

    return templates.TemplateResponse("loans/application_detail.html", {
        "request": request,
        "current_user": user,
        "active_tab": "loans",
        "app": dict(app_row),
        "member": dict(member),
        "manager_name": mgr_name,
        "approvals_history": [dict(a) for a in approvals_cur],
        "can_approve": can_appr,
        "is_own_application": is_own,
        "success": success,
        "error": error,
    })

@router.post("/loans/application/{app_id}/approve")
def loan_approve_submit(
    request: Request,
    app_id: int,
    decision: str = Form(...),
    comment: Optional[str] = Form(None),
):
    user = require_auth(request)
    try:
        process_approval(
            application_id=app_id,
            decision=decision,
            comment=comment or "",
            current_user=user,
        )
        return RedirectResponse(url=f"/loans/application/{app_id}?success=Keputusan+{decision}+berhasil+disimpan", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/loans/application/{app_id}?error={str(e)}", status_code=303)

@router.get("/loans/{loan_id}", response_class=HTMLResponse)
def loan_active_view(request: Request, loan_id: int, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    try:
        loan_data = get_loan_details(loan_id, user)
        return templates.TemplateResponse("loans/detail.html", {
            "request": request,
            "current_user": user,
            "active_tab": "loans",
            "loan": loan_data,
            "success": success,
            "error": error,
        })
    except Exception as e:
        return RedirectResponse(url=f"/loans?error={str(e)}", status_code=303)

@router.post("/loans/installment/{inst_id}/pay")
def loan_pay_installment_submit(
    request: Request,
    inst_id: int,
    paid_amount: str = Form(...),
    idempotency_key: str = Form(...),
):
    user = require_auth(request)
    try:
        res = pay_loan_installment(
            installment_id=inst_id,
            paid_amount_str=paid_amount,
            idempotency_key=idempotency_key,
            current_user=user,
        )
        with get_db() as conn:
            loan_id = conn.execute("SELECT loan_id FROM loan_installments WHERE id = ?", (inst_id,)).fetchone()["loan_id"]
        return RedirectResponse(url=f"/loans/{loan_id}?success=Angsuran+berhasil+dibayar.+Outstanding+tersisa:+Rp+{res['remaining_outstanding']}", status_code=303)
    except Exception as e:
        with get_db() as conn:
            loan_id = conn.execute("SELECT loan_id FROM loan_installments WHERE id = ?", (inst_id,)).fetchone()["loan_id"]
        return RedirectResponse(url=f"/loans/{loan_id}?error={str(e)}", status_code=303)

# Disbursement Views
@router.get("/disbursement", response_class=HTMLResponse)
def disbursement_view(request: Request, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    with get_db() as conn:
        waiting = conn.execute(
            """
            SELECT la.*, m.name as member_name, m.member_number, m.bank_account
            FROM loan_applications la
            JOIN members m ON la.member_id = m.id
            WHERE la.status = 'WAITING_DISBURSEMENT'
            ORDER BY la.id ASC
            """,
        ).fetchall()
    return templates.TemplateResponse("disbursement/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "disbursement",
        "queue": [dict(w) for w in waiting],
        "success": success,
        "error": error,
    })

@router.post("/disbursement/{app_id}")
def disbursement_submit(request: Request, app_id: int):
    user = require_auth(request)
    try:
        res = disburse_loan(application_id=app_id, current_user=user)
        return RedirectResponse(url=f"/loans/{res['loan_id']}?success=Pinjaman+{res['loan_number']}+berhasil+dicairkan!", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/disbursement?error={str(e)}", status_code=303)

# Public Document QR Verification View
@router.get("/verify/{token}", response_class=HTMLResponse)
def verify_document_view(request: Request, token: str):
    user = get_current_user_optional(request)
    ip = request.client.host if request.client else "127.0.0.1"
    res = verify_document_token(token=token, ip_address=ip)
    return templates.TemplateResponse("documents/verify.html", {
        "request": request,
        "current_user": user,
        "token": token,
        "result": res,
    })

# Reports Views
@router.get("/reports", response_class=HTMLResponse)
def reports_view(request: Request, tab: str = Query("savings")):
    user = require_auth(request)
    savings_rep = get_savings_ledger_report()
    fin_rep = get_financial_transactions_report()
    mem_rep = get_members_report()
    audit_rep = get_audit_trail_report()

    return templates.TemplateResponse("reports/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "reports",
        "active_subtab": tab,
        "savings_report": savings_rep,
        "financial_report": fin_rep,
        "members_report": mem_rep,
        "audit_report": audit_rep,
    })

# User Management (Super Admin)
@router.get("/users", response_class=HTMLResponse)
def users_list_view(request: Request, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    if ROLE_SUPER_ADMIN not in user["roles"]:
        return RedirectResponse(url="/dashboard?error=Akses+ditolak", status_code=303)

    with get_db() as conn:
        users = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
        user_list = []
        for u in users:
            r_cur = conn.execute(
                "SELECT r.code FROM roles r JOIN user_roles ur ON r.id = ur.role_id WHERE ur.user_id = ?",
                (u["id"],),
            ).fetchall()
            user_list.append({
                **dict(u),
                "roles": [r["code"] for r in r_cur],
            })

    return templates.TemplateResponse("users/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "users",
        "users": user_list,
        "success": success,
        "error": error,
    })

@router.post("/users/invite")
def users_invite_submit(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    roles: List[str] = Form(...),
):
    user = require_auth(request)
    if ROLE_SUPER_ADMIN not in user["roles"]:
        return RedirectResponse(url="/dashboard?error=Akses+ditolak", status_code=303)

    try:
        inv = create_user_invitation(email=email, full_name=full_name, role_codes=roles, creator_user_id=user["id"])
        return RedirectResponse(url=f"/users?success=Pengguna+berhasil+diundang.+Tautan+aktivasi:+/invite?token={inv['token']}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/users?error={str(e)}", status_code=303)

@router.post("/users/{target_id}/status")
def users_status_submit(request: Request, target_id: int, status: str = Form(...)):
    user = require_auth(request)
    if ROLE_SUPER_ADMIN not in user["roles"]:
        return RedirectResponse(url="/dashboard?error=Akses+ditolak", status_code=303)

    try:
        change_user_status(user_id=target_id, new_status=status, actor_user_id=user["id"])
        return RedirectResponse(url="/users?success=Status+pengguna+berhasil+diubah", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/users?error={str(e)}", status_code=303)

# Business Units (Toko & Fotocopy) Views
from app.reports.service import (
    get_all_units,
    submit_unit_report,
    verify_unit_report,
    get_unit_reports_list,
    get_consolidated_financial_summary,
    get_member_shu_breakdown,
)

@router.get("/business-units", response_class=HTMLResponse)
def business_units_index_view(request: Request, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    units = get_all_units()
    reports = get_unit_reports_list()
    return templates.TemplateResponse("reports/business_units.html", {
        "request": request,
        "current_user": user,
        "active_tab": "business_units",
        "units": units,
        "reports": reports,
        "success": success,
        "error": error,
    })

@router.get("/business-units/new-report", response_class=HTMLResponse)
def business_units_new_report_view(request: Request, unit_id: Optional[int] = None, error: Optional[str] = None):
    user = require_auth(request)
    units = get_all_units()
    return templates.TemplateResponse("reports/business_units_form.html", {
        "request": request,
        "current_user": user,
        "active_tab": "business_units",
        "units": units,
        "selected_unit_id": unit_id or (units[0]["id"] if units else 1),
        "today": datetime.utcnow().strftime("%Y-%m-%d"),
        "error": error,
    })

@router.post("/business-units/new-report")
def business_units_new_report_submit(
    request: Request,
    unit_id: int = Form(...),
    period_year: int = Form(...),
    period_month: int = Form(...),
    gross_revenue: str = Form(...),
    cogs: str = Form(...),
    operational_expenses: str = Form(...),
    cash_and_bank: str = Form(...),
    inventory_value: str = Form(...),
    receivables: str = Form(...),
    fixed_assets: str = Form(...),
    payables: str = Form("0"),
    unit_capital: str = Form("0"),
    cash_deposit_to_parent: str = Form("0"),
    deposit_date: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    user = require_auth(request)
    try:
        rep_id = submit_unit_report(
            unit_id=unit_id,
            period_type="MONTHLY",
            period_year=period_year,
            period_month=period_month,
            cash_and_bank=cash_and_bank,
            inventory_value=inventory_value,
            receivables=receivables,
            fixed_assets=fixed_assets,
            other_assets="0",
            payables=payables,
            unit_capital=unit_capital,
            gross_revenue=gross_revenue,
            cogs=cogs,
            operational_expenses=operational_expenses,
            cash_deposit_to_parent=cash_deposit_to_parent,
            deposit_date=deposit_date,
            notes=notes,
            current_user=user,
        )
        return RedirectResponse(url="/business-units?success=Laporan+keuangan+unit+berhasil+disimpan", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/business-units/new-report?error={str(e)}", status_code=303)

@router.post("/business-units/report/{report_id}/verify")
def business_units_verify_submit(request: Request, report_id: int):
    user = require_auth(request)
    try:
        verify_unit_report(report_id, user)
        return RedirectResponse(url="/business-units?success=Laporan+berhasil+diverifikasi+dan+setoran+kas+tercatat", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/business-units?error={str(e)}", status_code=303)

@router.get("/business-units/consolidation", response_class=HTMLResponse)
def business_units_consolidation_view(request: Request, year: int = Query(2026)):
    user = require_auth(request)
    shu_data = get_member_shu_breakdown(year=year)
    return templates.TemplateResponse("reports/business_units_consolidation.html", {
        "request": request,
        "current_user": user,
        "active_tab": "business_units",
        "data": shu_data["summary"],
        "shu_breakdown": shu_data,
    })

# Settings Views
from app.reports.service import (
    get_all_settings,
    update_settings_dict,
    backup_database,
)

@router.get("/settings", response_class=HTMLResponse)
def settings_view(request: Request, success: Optional[str] = None, error: Optional[str] = None):
    user = require_auth(request)
    if ROLE_SUPER_ADMIN not in user["roles"] and ROLE_ADMIN_KOPERASI not in user["roles"]:
        return RedirectResponse(url="/dashboard?error=Akses+pengaturan+khusus+Admin", status_code=303)

    settings = get_all_settings()
    return templates.TemplateResponse("settings/index.html", {
        "request": request,
        "current_user": user,
        "active_tab": "settings",
        "settings": settings,
        "success": success,
        "error": error,
    })

@router.post("/settings")
async def settings_submit(request: Request):
    user = require_auth(request)
    if ROLE_SUPER_ADMIN not in user["roles"] and ROLE_ADMIN_KOPERASI not in user["roles"]:
        return RedirectResponse(url="/dashboard?error=Akses+ditolak", status_code=303)

    form_data = await request.form()
    new_settings = {k: v for k, v in form_data.items()}
    try:
        update_settings_dict(new_settings, user)
        return RedirectResponse(url="/settings?success=Pengaturan+koperasi+berhasil+diperbarui", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/settings?error={str(e)}", status_code=303)

@router.get("/settings/backup")
def settings_backup_download(request: Request):
    user = require_auth(request)
    if ROLE_SUPER_ADMIN not in user["roles"] and ROLE_ADMIN_KOPERASI not in user["roles"]:
        return RedirectResponse(url="/dashboard?error=Akses+ditolak", status_code=303)

    content, filename = backup_database()
    return RawResponse(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
