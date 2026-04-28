from __future__ import annotations

from pathlib import Path

DEFAULT_KEY_DIR = Path.home() / ".yxl_lace"
DEFAULT_LANG_FILE = DEFAULT_KEY_DIR / "lang"
DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "zh")


_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "welcome": "Welcome to the P2P project. Here, you can experience a programmer-exclusive, serverless, end-to-end encrypted private chat.",
        "menu_title": "Please select your operation:",
        "menu_body": "(0) quit project         (1) create RSA key pair\n"
        "(2) connect user         (3) set default local port\n"
        "(4) save contact         (5) connect saved contact\n"
        "(6) switch language      (7) edit contact label\n",
        "select_prompt": "select> ",
        "invalid_choice": "Invalid option, please enter 0–7.",
        "bye": "Bye.",
        "input_empty": "Input cannot be empty.",
        "peer_pubkey_paste": "Paste peer RSA public key (PEM). Finish with a single line containing only '.' then press Enter:",
        "peer_pubkey_empty": "Public key is empty",
        "peer_ipv4_prompt": "Peer IPv4> ",
        "peer_port_prompt": "Peer port> ",
        "port_int_required": "Port must be an integer.",
        "port_range": "Port must be within 1–65535.",
        "pubkey_invalid": "Invalid public key: {err}",
        "pubkey_same": "Both public keys are identical. Did you paste your own key by mistake?",
        "local_port_show": "Local default port: {local_port}; peer: {host}:{peer_port}",
        "role_prefix": "Role: ",
        "role_initiator": "initiator (send UDP to peer port)",
        "role_responder": "responder (listen UDP on local port {local_port})",
        "udp_auth_start": "Starting UDP authentication…",
        "udp_auth_fail": "Authentication failed: {err}",
        "udp_handshake_fail": "UDP handshake failed: {err}",
        "udp_auth_ok": "UDP authentication succeeded. Entering UDP + AES-GCM chat…",
        "rsa_saved_priv": "Private key saved: {path}",
        "rsa_saved_pub": "Public key saved: {path}",
        "rsa_pub_share_hdr": "--- Public key (send to peer) ---",
        "default_port_current": "Current local default port (UDP listen): {port}",
        "default_port_prompt": "New port (1–65535, Enter to keep {port})> ",
        "default_port_unchanged": "Unchanged.",
        "default_port_saved": "Default port saved: {port} (written to {file})",
        "need_generate_key": "Local private key not found: {path}. Please select (1) to generate a key pair first.",
        "contact_id_prompt": "Contact id (e.g. alice)> ",
        "contact_label_prompt": "Label> ",
        "contact_saved": "Contact saved.",
        "contacts_empty": "No saved contacts.",
        "contacts_list_hdr": "Saved contacts:",
        "contact_choose_prompt": "Select contact number> ",
        "contact_connecting": "Connecting saved contact…",
        "lang_current": "Current language: {lang}",
        "lang_prompt": "Switch language (en/zh, Enter to keep {lang})> ",
        "lang_saved": "Language saved: {lang}",
        "lang_invalid": "Unsupported language. Choose: en / zh",
        "chat_ready": "UDP encrypted chat is ready: local {local} ↔ peer {peer_ip}:{peer_port}\nType /quit to exit.",
        "chat_msg_too_long": "Message too long (> {max_bytes} bytes). Please split it.",

        # Qt GUI
        "qt_title": "YXL-LACE GUI",
        "qt_ready": "Ready.",
        "qt_contacts": "Contacts",
        "qt_add": "Add",
        "qt_edit_label": "Edit label",
        "qt_connect": "Connect",
        "qt_peer_ipv4": "Peer IPv4",
        "qt_peer_port": "Peer port",
        "qt_local_port": "Local port",
        "qt_peer_pubkey": "Peer public key (PEM)",
        "qt_gen_keys": "Generate keys",
        "qt_connect_manual": "Connect (manual)",
        "qt_send": "Send",
        "qt_disconnect": "Disconnect",
        "qt_language": "Language",
        "qt_type_message": "Type message…",
        "qt_settings": "Settings",
        "qt_settings_title": "Settings",
        "qt_settings_hint": "Local port is shared for UDP listen/handshake. Language and port are saved to ~/.yxl_lace/.",
        "qt_settings_saved": "Settings saved. local_port={port}, lang={lang}",
        "qt_copy_public_key": "Copy public key",
        "qt_public_key_copied": "Public key copied to clipboard.",
        "qt_copy_public_key_failed": "Copy public key failed: {err}",
        "qt_keys_generated": "Keys generated. Public key copied to clipboard.",
        "qt_keys_generate_failed": "Failed to generate keys: {err}",
        "qt_info": "Info",
        "qt_error": "Error",
    },
    "zh": {
        "welcome": "欢迎使用该 P2P 项目：无中心服务器、端到端加密的私密聊天。",
        "menu_title": "请选择操作：",
        "menu_body": "(0) 退出项目         (1) 创建 RSA 密钥对\n"
        "(2) 连接用户         (3) 设置默认本地端口\n"
        "(4) 保存联系人       (5) 连接已保存联系人\n"
        "(6) 更换语言         (7) 修改联系人备注\n",
        "select_prompt": "select> ",
        "invalid_choice": "无效选项，请输入 0–7。",
        "bye": "再见。",
        "input_empty": "输入不能为空。",
        "peer_pubkey_paste": "请粘贴对方的 RSA 公钥（PEM）。粘贴完毕后单独一行输入一个英文句点 . 并回车结束：",
        "peer_pubkey_empty": "公钥为空",
        "peer_ipv4_prompt": "对方 IPv4> ",
        "peer_port_prompt": "对方端口> ",
        "port_int_required": "端口必须是整数。",
        "port_range": "端口须在 1–65535。",
        "pubkey_invalid": "公钥无效：{err}",
        "pubkey_same": "双方公钥相同，请确认未将本机公钥误贴为对方公钥",
        "local_port_show": "本机默认端口：{local_port}；对端：{host}:{peer_port}",
        "role_prefix": "本机角色：",
        "role_initiator": "先手（UDP 发往对方端口）",
        "role_responder": "后手（UDP 监听本机 {local_port}）",
        "udp_auth_start": "正在进行 UDP 认证…",
        "udp_auth_fail": "认证失败：{err}",
        "udp_handshake_fail": "UDP 握手失败：{err}",
        "udp_auth_ok": "UDP 认证成功。正在进入 UDP + AES-GCM 加密聊天…",
        "rsa_saved_priv": "已保存私钥：{path}",
        "rsa_saved_pub": "已保存公钥：{path}",
        "rsa_pub_share_hdr": "--- 公钥（请发给对方）---",
        "default_port_current": "当前本机默认通信端口（UDP 监听）：{port}",
        "default_port_prompt": "新端口 (1–65535，直接回车保持 {port})> ",
        "default_port_unchanged": "未修改。",
        "default_port_saved": "已保存默认端口：{port}（写入 {file}）",
        "need_generate_key": "未找到本地私钥：{path}，请先选择 (1) 生成密钥对。",
        "contact_id_prompt": "联系人 id（如 alice）> ",
        "contact_label_prompt": "备注/名称> ",
        "contact_saved": "联系人已保存。",
        "contacts_empty": "暂无已保存联系人。",
        "contacts_list_hdr": "已保存联系人：",
        "contact_choose_prompt": "选择联系人序号> ",
        "contact_connecting": "正在连接已保存联系人…",
        "lang_current": "当前语言：{lang}",
        "lang_prompt": "更换语言 (en/zh，直接回车保持 {lang})> ",
        "lang_saved": "已保存语言：{lang}",
        "lang_invalid": "不支持的语言，请选择：en / zh",
        "chat_ready": "UDP 加密聊天已就绪：本机 {local} ↔ 对端 {peer_ip}:{peer_port}\n输入 /quit 退出。",
        "chat_msg_too_long": "消息过长（> {max_bytes} bytes），请分段发送。",

        # Qt GUI
        "qt_title": "YXL-LACE 图形界面",
        "qt_ready": "就绪。",
        "qt_contacts": "联系人",
        "qt_add": "新增",
        "qt_edit_label": "修改备注",
        "qt_connect": "连接",
        "qt_peer_ipv4": "对端 IPv4",
        "qt_peer_port": "对端端口",
        "qt_local_port": "本机端口",
        "qt_peer_pubkey": "对端公钥（PEM）",
        "qt_gen_keys": "生成密钥",
        "qt_connect_manual": "手动连接",
        "qt_send": "发送",
        "qt_disconnect": "断开",
        "qt_language": "语言",
        "qt_type_message": "输入消息…",
        "qt_settings": "设置",
        "qt_settings_title": "设置",
        "qt_settings_hint": "本机端口用于 UDP 监听/握手（全局共享）。语言和端口会保存到 ~/.yxl_lace/。",
        "qt_settings_saved": "设置已保存。本机端口={port}，语言={lang}",
        "qt_copy_public_key": "复制公钥",
        "qt_public_key_copied": "公钥已复制到剪贴板。",
        "qt_copy_public_key_failed": "复制公钥失败：{err}",
        "qt_keys_generated": "密钥已生成，公钥已复制到剪贴板。",
        "qt_keys_generate_failed": "生成密钥失败：{err}",
        "qt_info": "提示",
        "qt_error": "错误",
    },
}


def get_lang() -> str:
    try:
        raw = DEFAULT_LANG_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return DEFAULT_LANG
    return raw if raw in SUPPORTED_LANGS else DEFAULT_LANG


def set_lang(lang: str) -> None:
    lang = lang.strip().lower()
    if lang not in SUPPORTED_LANGS:
        raise ValueError(lang)
    DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_LANG_FILE.write_text(lang, encoding="utf-8")


def t(key: str, **kwargs: object) -> str:
    lang = get_lang()
    tmpl = _TEXT.get(lang, _TEXT[DEFAULT_LANG]).get(key) or _TEXT[DEFAULT_LANG].get(key, key)
    return tmpl.format(**kwargs)


def logo_out() -> None:
    print(
        """
██    ██ ██   ██   ██
 ██  ██   ██ ██    ██
  ████     ███     ██
   ██     ██ ██    ██
   ██    ██   ██   ███████
""".rstrip("\n")
    )


def index_out() -> None:
    print(t("welcome"))


def operate_out() -> None:
    print(t("menu_title"))
    print(t("menu_body"), end="")

