"use client";

import { LockKeyhole, LogOut, ShieldCheck, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

type Role = "guest" | "public" | "private" | "admin";

const ROLE_LABELS: Record<Role, string> = {
  guest: "未登入",
  public: "公開帳號",
  private: "私人分析",
  admin: "管理者",
};

const MODULES: Array<{ name: string; minimumRole: Role }> = [
  { name: "公開評議書搜尋", minimumRole: "guest" },
  { name: "公開案件閱讀", minimumRole: "guest" },
  { name: "公開 AI 分析包", minimumRole: "guest" },
  { name: "私人案件管理", minimumRole: "private" },
  { name: "文件匯入", minimumRole: "private" },
  { name: "AI 分析結果", minimumRole: "private" },
  { name: "批次儀表板", minimumRole: "private" },
  { name: "模組權限管理", minimumRole: "admin" },
];

const ROLE_WEIGHT: Record<Role, number> = {
  guest: 0,
  public: 1,
  private: 2,
  admin: 3,
};

function canUse(role: Role, minimumRole: Role) {
  return ROLE_WEIGHT[role] >= ROLE_WEIGHT[minimumRole];
}

export function AuthMenu() {
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<Role>("guest");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const savedRole = window.localStorage.getItem("teacherAppealRole") as Role | null;
    if (savedRole && savedRole in ROLE_LABELS) {
      setRole(savedRole);
    }
  }, []);

  const visibleModules = useMemo(() => MODULES.filter((item) => canUse(role, item.minimumRole)), [role]);

  function login() {
    const normalized = username.trim().toLowerCase();
    if (!password.trim()) {
      setMessage("請輸入密碼。");
      return;
    }
    if (!["admin", "private", "public"].includes(normalized)) {
      setMessage("帳號請使用 admin、private 或 public。");
      return;
    }
    if (password !== "simisimi520") {
      setMessage("密碼不正確。");
      return;
    }
    const nextRole = normalized as Exclude<Role, "guest">;
    setRole(nextRole);
    window.localStorage.setItem("teacherAppealRole", nextRole);
    setPassword("");
    setMessage("已登入。");
  }

  function logout() {
    setRole("guest");
    window.localStorage.removeItem("teacherAppealRole");
    setPassword("");
    setMessage("已登出。");
  }

  return (
    <div className="auth-menu">
      <button className="auth-trigger" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        {role === "guest" ? <UserRound size={17} aria-hidden="true" /> : <ShieldCheck size={17} aria-hidden="true" />}
        {role === "guest" ? "登入" : ROLE_LABELS[role]}
      </button>
      {open ? (
        <div className="auth-panel">
          <div className="auth-panel-head">
            <div>
              <div className="auth-title">工作台登入</div>
              <div className="auth-caption">同一網址依權限顯示可用模組</div>
            </div>
            <LockKeyhole size={18} aria-hidden="true" />
          </div>

          {role === "guest" ? (
            <div className="auth-form">
              <label>
                帳號
                <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="admin / private / public" />
              </label>
              <label>
                密碼
                <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" />
              </label>
              <button className="button" type="button" onClick={login}>
                登入
              </button>
            </div>
          ) : (
            <div className="auth-session">
              <div className="auth-role">{ROLE_LABELS[role]}</div>
              <button className="button secondary" type="button" onClick={logout}>
                <LogOut size={16} aria-hidden="true" />
                登出
              </button>
            </div>
          )}

          {message ? <div className="auth-message">{message}</div> : null}

          <div className="module-list">
            <div className="auth-title small">目前可用模組</div>
            {visibleModules.map((item) => (
              <div className="module-row" key={item.name}>
                <span>{item.name}</span>
                <span>{ROLE_LABELS[item.minimumRole]}</span>
              </div>
            ))}
          </div>

          <div className="auth-note">
            Vercel 版目前提供公開查詢與登入入口；私人案件匯入、批次分析等完整功能需連到 Streamlit 工作台後端。
          </div>
        </div>
      ) : null}
    </div>
  );
}
