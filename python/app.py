import sqlite3
from smtplib import SMTP
from typing import List, Dict, Optional
import secrets  # pro krátký náhodný suffix

import pandas as pd
import streamlit as st

MAIL_CONFIG_PATH = "configMAIL.csv"

MAX_ROOMS = 6
# širší layout a sidebar

SIDEBAR_PX = 460  # můžeš si doladit (např. 420–480)

st.markdown(f"""
<style>
  [data-testid="stSidebar"] {{
    width: {SIDEBAR_PX}px !important;
    min-width: {SIDEBAR_PX}px !important;
  }}
  [data-testid="stSidebar"] .block-container {{
    padding-right: 16px;
  }}
  /* Čitelné psaní/čtení dlouhých mailů */
  [data-testid="stSidebar"] textarea {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 14px;
    line-height: 1.3;
    white-space: pre;       /* žádné zalamování; horizontální scroll když je řádek delší */
    overflow-wrap: normal;
  }}
</style>
""", unsafe_allow_html=True)


# --- CZ FONTY (ReportLab) ---
from pathlib import Path
from reportlab import rl_config
from reportlab.lib.fonts import addMapping  # ⬅️ důležité

FONT_DIR = Path("static/fonts")
FONT_REG = FONT_DIR / "DejaVuSans.ttf"
FONT_BLD = FONT_DIR / "DejaVuSans-Bold.ttf"
FONT_ITA = FONT_DIR / "DejaVuSans-Oblique.ttf"       # volitelné
FONT_BI  = FONT_DIR / "DejaVuSans-BoldOblique.ttf"   # volitelné

def ensure_czech_fonts() -> None:
    """
    Registruje TTF fonty pro češtinu a nastaví rodinné mapování, aby fungovalo bold/italic.
    Volat jednou při startu (v main()).
    """
    # ať ReportLab hledá i ve static/fonts
    try:
        rl_config.TTFSearchPath = list(dict.fromkeys(
            list(rl_config.TTFSearchPath) + [str(FONT_DIR.resolve()), str(Path(".").resolve())]
        ))
        rl_config.warnOnMissingFontGlyphs = 1
    except Exception:
        pass

    missing = []
    if not FONT_REG.exists(): missing.append(str(FONT_REG))
    if not FONT_BLD.exists(): missing.append(str(FONT_BLD))
    if missing:
        raise FileNotFoundError(
            "Chybí TTF fonty pro PDF.\n"
            + "\n".join(f"- {p}" for p in missing)
            + "\nVlož soubory do static/fonts (DejaVuSans.ttf a DejaVuSans-Bold.ttf)."
        )

    # registrace základních řezy
    if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(FONT_REG)))
    if "DejaVuSans-Bold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(FONT_BLD)))

    # volitelně registruj i italic/bold-italic, pokud tam jsou
    has_ita = False
    has_bi = False
    if FONT_ITA.exists():
        if "DejaVuSans-Oblique" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", str(FONT_ITA)))
        has_ita = True
    if FONT_BI.exists():
        if "DejaVuSans-BoldOblique" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVuSans-BoldOblique", str(FONT_BI)))
        has_bi = True

    # >>> KLÍČOVÉ: mapování rodiny (family/bold/italic) <<<
    addMapping("DejaVuSans", 0, 0, "DejaVuSans")
    addMapping("DejaVuSans", 1, 0, "DejaVuSans-Bold")
    addMapping("DejaVuSans", 0, 1, "DejaVuSans-Oblique" if has_ita else "DejaVuSans")
    addMapping("DejaVuSans", 1, 1, "DejaVuSans-BoldOblique" if has_bi else "DejaVuSans-Bold")

    # (volitelné, ale nevadí): zaregistruj rodinu i přes pdfmetrics
    try:
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily(
            "DejaVuSans",
            normal="DejaVuSans",
            bold="DejaVuSans-Bold",
            italic=("DejaVuSans-Oblique" if has_ita else "DejaVuSans"),
            boldItalic=("DejaVuSans-BoldOblique" if has_bi else "DejaVuSans-Bold"),
        )
    except Exception:
        pass


from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent


SITES = {
    "Hejnice": {
        "db":     str(BASE_DIR / "reservations_hejnice.db"),
        "config": str(BASE_DIR / "config_Hejnice.csv"),  # nebo Hejnice.csv, pokud tak chceš
    },
    "Dobřejov": {
        "db":     str(BASE_DIR / "reservations_dobrejov.db"),
        "config": str(BASE_DIR / "config_Dobřejov.csv"),
    },
}
MAIL_CONFIG_PATH = str(BASE_DIR / "configMAIL.csv")

CZ_MONTHS = [
    "",  # index 0 prázdný (aby 1=leden)
    "Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
    "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec"
]

import re


def _valid_email(addr: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", addr or ""))

@st.cache_data(show_spinner=False)
def load_mail_config(path: str, file_mtime: float) -> dict:
    fallback = {
        "EMAIL": (st.secrets.get("RECIPIENT_EMAIL") or "").strip(),
        "SUBJECT_VOUCHER": "",
        "SUBJECT_PARTICIPANTS": "",
        "BODY_VOUCHER": "",
        "BODY_PARTICIPANTS": "",
    }
    from pathlib import Path
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return fallback

    import pandas as pd
    try:
        df = pd.read_csv(p, encoding="utf-8", sep=None, engine="python")  # autodetekce , ; \t
    except Exception:
        df = pd.read_csv(p, encoding="cp1250", sep=None, engine="python")

    df.columns = [str(c).strip().upper() for c in df.columns]
    if "EMAIL" not in df.columns:
        return fallback

    df_nonempty = df[df["EMAIL"].fillna("").astype(str).str.strip() != ""]
    if df_nonempty.empty:
        return fallback

    row = df_nonempty.iloc[0]
    return {
        "EMAIL": str(row.get("EMAIL", "")).strip(),
        "SUBJECT_VOUCHER": str(row.get("SUBJECT_VOUCHER", "") or "").strip(),
        "SUBJECT_PARTICIPANTS": str(row.get("SUBJECT_PARTICIPANTS", "") or "").strip(),
        "BODY_VOUCHER": str(row.get("BODY_VOUCHER", "") or "").strip(),
        "BODY_PARTICIPANTS": str(row.get("BODY_PARTICIPANTS", "") or "").strip(),
    }

def get_mail_recipient() -> tuple[str, dict]:
    from pathlib import Path
    p = Path(MAIL_CONFIG_PATH)
    mtime = p.stat().st_mtime if p.exists() else 0.0
    cfg = load_mail_config(MAIL_CONFIG_PATH, mtime)
    email = cfg.get("EMAIL", "")
    if not email:
        st.error("Adresát e-mailu není definován: doplňte EMAIL v configMAIL.csv nebo RECIPIENT_EMAIL ve st.secrets.")
    return email, cfg


def send_email_with_attachment(to_email: str, subject: str, body: str,
                               attachment_bytes: bytes, filename: str) -> None:
    import smtplib, ssl
    from email.message import EmailMessage

    host = st.secrets.get("SMTP_HOST")
    port = int(st.secrets.get("SMTP_PORT", 25))
    user = st.secrets.get("SMTP_USER")
    pwd  = st.secrets.get("SMTP_PASS")
    from_addr = (st.secrets.get("SMTP_FROM") or user or "").strip()

    if not all([host, port, user, pwd, from_addr]):
        raise RuntimeError("Chybí SMTP parametry ve st.secrets (SMTP_HOST/PORT/USER/PASS/FROM).")

    if not _valid_email(to_email):
        raise ValueError("Neplatná e-mailová adresa.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.set_content(body)
    msg.add_attachment(attachment_bytes, maintype="application", subtype="pdf", filename=filename)

    # 465 => SSL; jinak STARTTLS. Možno přepnout přes SMTP_SSL=true/false v secrets.
    secure_override = str(st.secrets.get("SMTP_SSL", "")).lower()
    use_ssl = False
    timeout = int(st.secrets.get("SMTP_TIMEOUT", 20))
    context = ssl.create_default_context()

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                server.login(user, "")
                server.send_message(msg)
        else:
            server: SMTP
            with smtplib.SMTP(host, port, timeout=timeout) as server:
              server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise RuntimeError(f"SMTP autentizace selhala: {e}") from e
    except smtplib.SMTPConnectError as e:
        raise RuntimeError(f"SMTP spojení selhalo: {e}") from e
    except Exception as e:
        raise RuntimeError(f"SMTP chyba: {e}") from e




def _shift_month(delta: int):
    """Posune aktivní měsíc o delta (záporné/dkladné) a zajistí přetečení roku."""
    y = int(st.session_state.get("cal_year", date.today().year))
    m = int(st.session_state.get("cal_month", date.today().month))
    m += delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    st.session_state["cal_year"]  = y
    st.session_state["cal_month"] = m

# --- ROLES / AUTH (JEDINÝ ZDROJ PRAVDY) ---
def current_role() -> str:
    return st.session_state.get("role", "public")  # 'admin' | 'dohled' | 'public'

def is_admin() -> bool:
    return current_role() == "admin"

def is_dohled() -> bool:
    return current_role() == "dohled"

def logout_role():
    st.session_state["role"] = "public"
    # volitelně vynuluj výběr stránky, ať nesetrvává stará stránka
    st.session_state["nav"] = None

def login_box():
    # CSS: posuň sidebar obsah nahoru a ukliď vzhled expanderu (schovej šipku)
    st.sidebar.markdown("""
    <style>
      [data-testid="stSidebar"] .block-container { padding-top: 6px !important; }
      /* schovej šipečku expanderu */
      [data-testid="stSidebar"] [data-testid="stExpander"] summary svg { display: none !important; }
      /* zmenši hlavičku expanderu, ať je to jen ikonka */
      [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        padding: 4px 6px !important;
      }
      /* ikonka jako „tlačítko“ */
      .lock-badge {
        display:inline-block; padding:6px 8px; border-radius:8px;
        background:#eef2ff; color:#1e3a8a; font-weight:700; text-decoration:none;
      }
      .lock-badge:hover { background:#dbeafe; }
    </style>
    """, unsafe_allow_html=True)

    # expander s čistou ikonkou (žádný text)
    with st.sidebar.expander("🔐", expanded=False):
        st.markdown('<span class="lock-badge">Správcovský režim</span>', unsafe_allow_html=True)
        role_choice = st.radio("Režim", ["Dohled", "Admin"], horizontal=True, key="login_role_choice")
        pwd = st.text_input("Heslo", type="password", key="login_pwd")

        if st.button("Přihlásit", key="login_btn"):
            admin_secret  = st.secrets.get("ADMIN_PASSWORD", "")
            dohled_secret = st.secrets.get("DOHLED_PASSWORD", "")

            if role_choice == "Admin":
                if pwd and admin_secret and pwd == admin_secret:
                    st.session_state["role"] = "admin"
                    st.session_state["nav"] = None
                    st.success("Správcovský režim (Admin) aktivní.")
                    st.rerun()
                else:
                    st.error("Neplatné heslo pro Admin.")
            else:
                if pwd and dohled_secret and pwd == dohled_secret:
                    st.session_state["role"] = "dohled"
                    st.session_state["nav"] = None
                    st.success("Režim dohledu aktivní.")
                    st.rerun()
                else:
                    st.error("Neplatné heslo pro Dohled.")

        st.caption("Běžný uživatel nic vyplňovat nemusí.")


def current_paths():
    """Vrátí (db_path, config_path) pro aktuální lokalitu ze session_state."""
    site = st.session_state.get("site")
    if not site or site not in SITES:
        return None, None
    return SITES[site]["db"], SITES[site]["config"]

def save_config(df: pd.DataFrame):
    _, cfg_path = current_paths()
    assert_writing_to_current_config(cfg_path)
    df.to_csv(cfg_path, index=False, encoding="utf-8")


def assert_writing_to_current_config(target_path: str):
    """Zabrání omylu: povolí zapisovat jen do aktuálního configu vybrané lokality."""
    _, cfg_path = current_paths()
    if not cfg_path:
        raise RuntimeError("Lokalita není zvolena.")
    from pathlib import Path
    if Path(target_path).resolve() != Path(cfg_path).resolve():
        raise RuntimeError(f"Zápis do nepovoleného souboru: {target_path}. Aktivní je {cfg_path}.")

def counter_in_form(col, key: str, label: str = "", min_value: int = 0) -> int:
    # inicializace
    if key not in st.session_state:
        st.session_state[key] = 0

    b_minus, b_val, b_plus = col.columns([1, 2, 1])

    # tlačítka v rámci FORM – musí být form_submit_button
    dec = b_minus.form_submit_button("−", key=f"{key}_dec")
    inc = b_plus.form_submit_button("+", key=f"{key}_inc")

    # vlastní číslo (můžeš i ručně přepsat)
    v = b_val.number_input(
        label or key,
        min_value=min_value,
        step=1,
        value=int(st.session_state[key]),
        key=f"{key}_num",
        label_visibility="collapsed",
    )

    # sync ručního přepisu
    if int(v) != st.session_state[key]:
        st.session_state[key] = int(v)

    # kliky na ± jen upraví stav; formulář se sice “odeslal”, ale neuložíme nic
    if dec:
        st.session_state[key] = max(min_value, int(st.session_state[key]) - 1)
    if inc:
        st.session_state[key] = int(st.session_state[key]) + 1

    return int(st.session_state[key])

import streamlit as st

def site_login_ui():
    # logo ZOO Praha vpravo nahoře
    logo = Path("static/zoo_logo.png")
    if logo.exists() and logo.stat().st_size > 0:
        col_logo = st.columns([9,1])  # levý prázdný prostor, pravý pro logo
        with col_logo[1]:
            st.image(str(logo), width=120)

    st.title("Rezervace – výběr lokality")
    st.write("Vyberte objekt, se kterým chcete pracovat:")

    h_path = Path("static/hejnice.jpg")
    d_path = Path("static/dobrejov.jpg")

    c1, c2 = st.columns(2)
    site = None

    with c1:
        if h_path.exists() and h_path.stat().st_size > 0:
            st.image(str(h_path), use_container_width=True)
        else:
            st.info("Obrázek Hejnice nenalezen (static/hejnice.jpg).")
        if st.button("Hejnice", key="pick_hejnice", use_container_width=True):
            site = "Hejnice"

    with c2:
        if d_path.exists() and d_path.stat().st_size > 0:
            st.image(str(d_path), use_container_width=True)
        else:
            st.info("Obrázek Dobřejov nenalezen (static/dobrejov.jpg).")
        if st.button("Dobřejov", key="pick_dobrejov", use_container_width=True):
            site = "Dobřejov"

    if site:
        role = st.session_state.get("role", "public")
        st.session_state.clear()
        st.session_state["role"] = role
        st.session_state["site"] = site
        st.rerun()

# ---------- DB ----------
from datetime import date
from typing import Optional
from datetime import datetime as _dt

def booking_form_unified(mode: str = "admin", edit_id: Optional[str] = None):
    """
    Jeden UI formulář pro veřejnost i admina.
      - mode="public": uloží žádost do `requests` (vč. rooms_json, per_room) + nezávaznost
      - mode="admin":  uloží/přepíše rezervaci do `reservations` + `reservation_rooms`
    """
    assert mode in ("admin", "public")
    cfg = get_cfg()
    st.header("Rezervace" if mode == "admin" else "Žádost o rezervaci (stejný formulář)")
    # ——— flash zpráva po úspěšném uložení ———
    _flash = st.session_state.pop("flash_success", None)
    if _flash:
        st.success(_flash)
        st.info("Formulář je prázdný, můžeš zadat další rezervaci.")
        return

    # ===== per-room přepínač mimo form (okamžitý rerender) =====
    if "per_room_mode" not in st.session_state:
        st.session_state["per_room_mode"] = False
    prev_mode = st.session_state["per_room_mode"]

    per_room = st.checkbox("Vlastní datumy pro každý pokoj (per-room)",
                           value=prev_mode, key="per_room_mode")

    # jednorázové zkopírování globálních dat do per-room při přepnutí
    if per_room != prev_mode:
        if per_room and "global_arrival_tmp" in st.session_state and "global_departure_tmp" in st.session_state:
            for i in range(1, MAX_ROOMS + 1):
                st.session_state[f"arr_{i}"] = st.session_state["global_arrival_tmp"]
                st.session_state[f"dep_{i}"] = st.session_state["global_departure_tmp"]
        st.rerun()

    # ===== globální datumy (jen když není per-room) =====
    if not per_room:
        cga, cgd = st.columns(2)
        global_arrival = cga.date_input("Příjezd", value=date.today(),
                                        format="DD.MM.YYYY", key="global_arrival_tmp")
        global_departure = cgd.date_input("Odjezd", value=date.today(),
                                          format="DD.MM.YYYY", key="global_departure_tmp")
        global_nights = max(0, days_between(global_arrival, global_departure))
        st.write(f"Nocí: **{global_nights}**")
    else:
        global_arrival = None
        global_departure = None
        global_nights = 0

    # ===== FORM =====
    with st.form(f"booking_form_{mode}"):
        # Základní údaje
        c1, c2 = st.columns(2)
        guest_name = c1.text_input(
            "Jméno a příjmení",
            value=st.session_state.get("guest_name_prefill", "") if mode == "admin" else ""
        )

        contact = ""
        if mode == "public":
            contact = c2.text_input("Kontakt (e-mail/telefon)*", key="contact_pub")
        else:
            if edit_id:
                c2.text_input("ID rezervace", value=edit_id, disabled=True,
                              help="ID nelze měnit v režimu úprav.")
            else:
                c2.text_input("ID rezervace", value="(bude přiděleno při uložení)", disabled=True)

        # Pokoje + ceny (živý přepočet)
        rooms_payload = rooms_form(per_room, cfg, global_arrival, global_departure)

        note = ""
        consent = True
        if mode == "public":
            st.markdown("---")
            note = st.text_area("Zpráva pro ubytování (nepovinné)", key="note_pub",
                                placeholder="Upřesnění přání, požadavky, diety apod.")

            # ✅ Anchor uvnitř formu (OK), žádný download_button tady!
            consent = st.checkbox(
                "Odesláním žádosti souhlasím s dodržováním pravidel stanovených kolektivní smlouvou.",
                value=False, key="consent_pub"
            )

            st.info("Toto je **nezávazná registrace**. Po posouzení kapacit vám dáme vědět s potvrzením/úpravou.")

        st.markdown("---")
        btn_label = "Uložit rezervaci" if mode == "admin" else "Odeslat žádost"

        if mode == "public":
            col_submit, col_dl = st.columns([1, 1])
            save_clicked = col_submit.form_submit_button(btn_label)

            # „modré tlačítko“ – stylovaný odkaz na PDF
            if ks_exists():
                col_dl.markdown(
                    f"""
                    <a href="{ks_url()}" target="_blank"
                       style="
                         display:inline-block; padding:.55rem .9rem;
                         border:1px solid #2563eb; background:#7696db; color:#fff;
                         border-radius:8px; text-decoration:none; font-weight:600;
                         text-align:center;">
                      Stáhnout kolektivní smlouvu (PDF)
                    </a>
                    """,
                    unsafe_allow_html=True
                )
            else:
                col_dl.caption("Soubor smlouvy není k dispozici.")
        else:
            save_clicked = st.form_submit_button(btn_label)

    # ===== Uložení =====
    if not save_clicked:
        return

    # základní validace
    if not guest_name.strip():
        st.error("Vyplň jméno.")
        return
    if mode == "public" and not contact.strip():
        st.error("Vyplň kontakt.")
        return
    if len(rooms_payload) == 0:
        st.error("Vyber aspoň jeden pokoj (vyplň typ).")
        return

    # validace datumů/nocí (globální i per-room)
    ok, msg = validate_dates_and_nights(per_room, global_arrival, global_departure, rooms_payload)
    if not ok:
        st.error(msg)
        return

    if mode == "admin":
        # === ADMIN FLOW → REZERVACE ===
        booking_id = edit_id or new_booking_id()
        header = {
            "id": booking_id.strip(),
            "guest_name": guest_name.strip(),
            "global_arrival": global_arrival.strftime("%d.%m.%Y") if global_arrival else None,
            "global_departure": global_departure.strftime("%d.%m.%Y") if global_departure else None,
            "global_nights": (max(0, days_between(global_arrival, global_departure)) if not per_room else 0),
            "per_room": per_room
        }
        try:
            insert_or_replace_booking(header, rooms_payload, overwrite=bool(edit_id))

            # ➜ místo prostého st.success:
            msg = "Rezervace úspěšně vložena"  # bez ID, jak sis přál
            role = st.session_state.get("role", "admin")
            site = st.session_state.get("site")

            st.session_state.clear()
            st.session_state["role"] = role
            st.session_state["site"] = site
            st.session_state["nav"] = "Přidat/Upravit"  # zůstaň na stejné sekci
            st.session_state["flash_success"] = msg

            st.rerun()

        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Uložení selhalo: {e}")
        return

    # === PUBLIC FLOW → REQUESTS ===
    if not consent:
        st.error("Pro odeslání je nutné potvrdit souhlas s kolektivní smlouvou.")
        return

    # souhrnné hodnoty pro requests
    people_total = sum(int(r.get("employees", 0)) + int(r.get("guests", 0)) for r in rooms_payload)

    if per_room:
        # agregace: min(arrival) a max(departure) přes zadané pokoje
        dates_a = [_parse_cz_date(r.get("arrival")) for r in rooms_payload if r.get("arrival")]
        dates_d = [_parse_cz_date(r.get("departure")) for r in rooms_payload if r.get("departure")]
        a_min = min(dates_a) if dates_a else None
        d_max = max(dates_d) if dates_d else None
        arrival_str   = a_min.strftime("%d.%m.%Y") if a_min else ""
        departure_str = d_max.strftime("%d.%m.%Y") if d_max else ""
        nights_sumary = max(0, days_between(a_min, d_max)) if (a_min and d_max) else 0
    else:
        arrival_str   = global_arrival.strftime("%d.%m.%Y") if global_arrival else ""
        departure_str = global_departure.strftime("%d.%m.%Y") if global_departure else ""
        nights_sumary = max(0, days_between(global_arrival, global_departure)) if (global_arrival and global_departure) else 0

    req_id = new_request_id()
    created_at = _dt.now(ZoneInfo("Europe/Prague")).strftime("%Y-%m-%d %H:%M:%S")

    # JSON jen s potřebnými poli (konsolidovaný detail pokojů)
    rooms_for_json = [
        {
            "room_type": r.get("room_type", ""),
            "employees": int(r.get("employees", 0)),
            "guests":    int(r.get("guests", 0)),
            "arrival":   r.get("arrival", ""),
            "departure": r.get("departure", ""),
            "nights":    int(r.get("nights", 0)),
        } for r in rooms_payload
    ]

    try:
        with get_conn() as con:
            con.execute("""
                INSERT INTO requests(
                    req_id, guest_name, contact, arrival, departure,
                    nights, people, created_at, status, note, rooms_json, per_room
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                req_id, guest_name.strip(), contact.strip(),
                arrival_str, departure_str, int(nights_sumary), int(people_total),
                created_at, "nová", (note or "").strip(),
                json.dumps(rooms_for_json, ensure_ascii=False),
                1 if per_room else 0
            ))
            con.commit()
        msg = "Žádost byla úspěšně odeslána"  # text banneru po reloadu
        role = st.session_state.get("role", "public")
        site = st.session_state.get("site")

        # vyčistit formulář a ponechat kontext
        st.session_state.clear()
        st.session_state["role"] = role
        st.session_state["site"] = site
        st.session_state["nav"] = "Žádost o rezervaci"
        st.session_state["flash_success"] = msg

        st.rerun()
    except sqlite3.OperationalError as e:
        st.error("Chybí sloupce `rooms_json` nebo `per_room` v tabulce `requests`. "
                 "Přidej je prosím přes ALTER TABLE v init_db().")
    except Exception as e:
        st.error(f"Odeslání se nezdařilo: {e}")


def get_conn():
    db_path, _ = current_paths()
    if not db_path:
        raise RuntimeError("Lokalita není zvolena.")
    return sqlite3.connect(db_path, check_same_thread=False)

from pathlib import Path

@st.cache_data(show_spinner=False)
def load_config_for_path(config_path: str, file_mtime: float) -> pd.DataFrame:
    df = pd.read_csv(config_path, encoding="utf-8")
    df.columns = [c.strip().upper() for c in df.columns]
    for req in ("POKOJ", "CENA_Z", "CENA_N"):
        if req not in df.columns:
            raise ValueError(f"V configu chybí sloupec: {req}")
    return df

def get_cfg() -> pd.DataFrame:
    _, cfg_path = current_paths()
    if not cfg_path:
        raise RuntimeError("Lokalita není zvolena.")
    mtime = Path(cfg_path).stat().st_mtime  # ⬅️ při změně CSV se změní i cache klíč
    return load_config_for_path(cfg_path, mtime)


def new_booking_id(prefix: str = "RES") -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Europe/Prague"))
    ts = now.strftime("%Y%m%d-%H%M%S")
    suf = secrets.token_hex(2).upper()
    return f"{prefix}-{ts}-{suf}"

def init_db():
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id TEXT NOT NULL UNIQUE,
            guest_name TEXT NOT NULL,
            global_arrival TEXT,
            global_departure TEXT,
            global_nights INTEGER,
            per_room INTEGER NOT NULL DEFAULT 0
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reservation_rooms (
            id TEXT NOT NULL,
            room_idx INTEGER NOT NULL,
            room_type TEXT,
            employees INTEGER,
            guests INTEGER,
            arrival TEXT,
            departure TEXT,
            nights INTEGER,
            price REAL
        )""")
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS requests
                    (
                        req_id
                        TEXT
                        PRIMARY
                        KEY,
                        guest_name
                        TEXT
                        NOT
                        NULL,
                        contact
                        TEXT,
                        arrival
                        TEXT,
                        departure
                        TEXT,
                        nights
                        INTEGER,
                        people
                        INTEGER,
                        created_at
                        TEXT
                        NOT
                        NULL,
                        status
                        TEXT
                        NOT
                        NULL
                        DEFAULT
                        'nová', -- nová | schváleno | zamítnuto | vyřízeno
                        note
                        TEXT
                    )
                    """)
        try:
            cur.execute("ALTER TABLE requests ADD COLUMN rooms_json TEXT")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE requests ADD COLUMN per_room INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        con.commit()
        # NOVÉ: účastníci (per-person)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id TEXT NOT NULL,               -- booking ID
            person_idx INTEGER NOT NULL,    -- pořadí (1..N)
            name TEXT NOT NULL,
            is_employee INTEGER NOT NULL,   -- 1 = zaměstnanec, 0 = host
            nights INTEGER NOT NULL,
            room_type TEXT,                 -- pro výpočet ceny
            price REAL NOT NULL
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_res_id ON reservations(id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_resrooms_id ON reservation_rooms(id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_part_id ON participants(id)")
        try:
            cur.execute("ALTER TABLE requests ADD COLUMN rooms_json TEXT DEFAULT NULL;")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE requests ADD COLUMN per_room INTEGER NOT NULL DEFAULT 0;")
        except Exception:
            pass
        con.commit()


def participant_price(room_type: str, is_employee: bool, nights: int, cfg: pd.DataFrame) -> float:
    if not room_type or nights <= 0:
        return 0.0
    row = cfg[cfg["POKOJ"] == room_type]
    if row.empty:
        return 0.0
    per_night = float(row["CENA_Z"].iloc[0]) if is_employee else float(row["CENA_N"].iloc[0])
    return per_night * nights

def count_people_in_booking(booking_id: str) -> int:
    with get_conn() as con:
        df = pd.read_sql_query("""
            SELECT COALESCE(SUM(employees),0) AS emp, COALESCE(SUM(guests),0) AS gue
            FROM reservation_rooms
            WHERE id = ?
        """, con, params=(booking_id,))
    if df.empty:
        return 0
    return int(df.loc[0, "emp"] + df.loc[0, "gue"])

def fetch_booking_rooms(booking_id: str) -> pd.DataFrame:
    with get_conn() as con:
        df = pd.read_sql_query("""
            SELECT room_idx, room_type, employees, guests, arrival, departure, nights
            FROM reservation_rooms
            WHERE id = ?
            ORDER BY room_idx
        """, con, params=(booking_id,))
    return df

def delete_participants_by_id(booking_id: str):
    with get_conn() as con:
        con.execute("DELETE FROM participants WHERE id = ?", (booking_id,))
        con.commit()

def insert_participants(booking_id: str, payload: list[dict]):
    with get_conn() as con:
        cur = con.cursor()
        for p in payload:
            cur.execute("""
                INSERT INTO participants(id, person_idx, name, is_employee, nights, room_type, price)
                VALUES(?,?,?,?,?,?,?)
            """, (
                booking_id,
                int(p["person_idx"]),
                p["name"],
                1 if p["is_employee"] else 0,
                int(p["nights"]),
                p.get("room_type", ""),
                float(p.get("price", 0.0)),
            ))
        con.commit()

def participants_ui():
    st.header("Účastníci rezervace")

    # ID + jméno pro přehlednost
    with get_conn() as con:
        rows = con.execute("SELECT id, guest_name FROM reservations ORDER BY id DESC").fetchall()
    if not rows:
        st.info("Zatím nejsou žádné rezervace.")
        return

    labels = [f"{r[0]} — {r[1]}" for r in rows]
    map_label_to_id = {labels[i]: rows[i][0] for i in range(len(labels))}

    c1, c2 = st.columns([2,1])
    chosen = c1.selectbox("Vyber rezervaci", labels)
    booking_id = map_label_to_id[chosen]
    pref_df = fetch_booking_rooms(booking_id)

    # kolik lidí má mít účastnická tabulka (default = součet emp+guests)
    total_people_default = count_people_in_booking(booking_id)
    total_people = c2.number_input("Počet účastníků", min_value=1, value=max(1, total_people_default), step=1)

    # seznam dostupných typů pokojů z této rezervace (ne z celého ceníku → jasné ceny)
    room_types_in_booking = [rt for rt in pref_df["room_type"].dropna().unique().tolist() if rt] or get_cfg()["POKOJ"].tolist()
    cfg = get_cfg()

    st.markdown("**Zadej údaje účastníků:**")
    # default nocí – podle režimu rezervace
    hdr, _ = fetch_detail(booking_id)
    _, _, garr, gdep, gnights, per_room_flag = hdr
    default_nights = int(gnights or 0)

    # pokud per-room a máme víc typů/nocí, dáme default 1 noc a necháme upravit
    if per_room_flag == 1 and (pref_df["nights"].nunique() > 1):
        default_nights = 1

    # načti existující účastníky (předvyplníme, pokud existují)
    existing = fetch_participants(booking_id)

    participant_rows = []
    # hlavička tabulky
    head = st.columns([3, 2, 2, 2, 2])
    head[0].markdown("**Jméno účastníka**")
    head[1].markdown("**Zaměstnanec?**")
    head[2].markdown("**Nocí**")
    head[3].markdown("**Typ pokoje**")
    head[4].markdown("**Cena (Kč)**")

    total_price = 0.0

    for i in range(1, int(total_people) + 1):
        row = st.columns([3, 2, 2, 2, 2])

        # předvyplnění, pokud existuje v DB
        if not existing.empty and i <= len(existing):
            ex = existing.iloc[i-1]
            name_init = ex["name"]
            is_emp_init = bool(ex["is_employee"])
            nights_init = int(ex["nights"])
            room_type_init = ex["room_type"] if ex["room_type"] in room_types_in_booking else (room_types_in_booking[0] if room_types_in_booking else "")
        else:
            name_init = ""
            is_emp_init = False
            # per-room → zkusíme namapovat podle pořadí na pokoj s nocemi
            if per_room_flag == 1 and not pref_df.empty and i <= len(pref_df):
                nights_init = int(pref_df.iloc[i-1]["nights"] or default_nights or 0)
                room_type_init = pref_df.iloc[i-1]["room_type"] or (room_types_in_booking[0] if room_types_in_booking else "")
            else:
                nights_init = int(default_nights or 0)
                room_type_init = room_types_in_booking[0] if room_types_in_booking else ""

        name_val = row[0].text_input(f"Jméno {i}", value=name_init, key=f"p_name_{booking_id}_{i}")
        is_emp_val = row[1].checkbox(f"Zam. {i}", value=is_emp_init, key=f"p_emp_{booking_id}_{i}")
        nights_val = row[2].number_input(f"Nocí {i}", min_value=0, step=1, value=nights_init, key=f"p_nights_{booking_id}_{i}")
        room_type_val = row[3].selectbox(f"Pokoj {i}", room_types_in_booking, index=(room_types_in_booking.index(room_type_init) if room_type_init in room_types_in_booking else 0), key=f"p_room_{booking_id}_{i}")

        price_val = int(participant_price(room_type_val, is_emp_val, nights_val, cfg))
        row[4].write(price_val)

        participant_rows.append({
            "person_idx": i,
            "name": name_val.strip(),
            "is_employee": bool(is_emp_val),
            "nights": int(nights_val),
            "room_type": room_type_val,
            "price": float(price_val),
        })
        total_price += price_val

    st.markdown(f"**Součet za účastníky:** {int(total_price)} Kč")

    csave, cvoucher = st.columns([1,1])
    if csave.button("Uložit účastníky"):
        # validace: jména + nenulové noci
        for p in participant_rows:
            if not p["name"]:
                st.error("Vyplň jména všech účastníků.")
                return
            if p["nights"] <= 0:
                st.error("Počet nocí musí být ≥ 1 u všech účastníků.")
                return
        try:
            delete_participants_by_id(booking_id)
            insert_participants(booking_id, participant_rows)
            st.success("Účastníci uloženi.")
        except Exception as e:
            st.error(f"Ukládání selhalo: {e}")

    if cvoucher.button("Vygenerovat poukaz (účastníci)"):
        try:
            pdf_bytes = create_voucher_pdf_bytes_participants(booking_id)
            st.success("Poukaz vygenerován.")
            st.download_button(
                label="Stáhnout poukaz PDF",
                data=pdf_bytes,
                file_name=f"poukaz_ucastnici_{booking_id}.pdf",
                mime="application/pdf",
            )
        except Exception as e:
            st.error(f"Generování selhalo: {e}")

        # --- odeslání poukazu účastníků e-mailem ---
        st.markdown("---")
        st.subheader("Odeslat poukaz účastníků e-mailem")

        recipient2, mcfg2 = get_mail_recipient()
        st.caption(f"Adresát e-mailu: **{recipient2 or 'nenalezen'}** (configMAIL.csv)")
        send2 = st.button("Odeslat e-mailem (účastníci)", key=f"participants_send_{booking_id}")

        if send2:
            if not recipient2:
                st.error("Nelze odeslat: chybí e-mail v configMAIL.csv.")
                return
            try:
                pdf_bytes2 = create_voucher_pdf_bytes_participants(booking_id)
                subj2 = mcfg2.get("SUBJECT_PARTICIPANTS") or f"Poukaz (účastníci) k rezervaci {booking_id}"
                body2 = mcfg2.get(
                    "BODY_PARTICIPANTS") or "Dobrý den,\n\nv příloze zasíláme poukaz (účastníci) k rezervaci.\n\nS pozdravem\nHejnice/Dobřejov"
                send_email_with_attachment(recipient2, subj2, body2, pdf_bytes2, f"poukaz_ucastnici_{booking_id}.pdf")
                st.success(f"E-mail odeslán na {recipient2}.")
            except Exception as e:
                st.error(f"Odeslání e-mailu selhalo: {e}")


def create_voucher_pdf_bytes_participants(booking_id: str) -> bytes:
    # Unicode fonty...

    ensure_czech_fonts()

    hdr, _ = fetch_detail(booking_id)
    if not hdr:
        raise ValueError("ID nenalezeno.")
    _id, guest_name, garr, gdep, gnights, per_room = hdr
    parts = fetch_participants(booking_id)
    if parts.empty:
        raise ValueError("Nejsou uložení žádní účastníci.")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    base_font = "DejaVuSans"
    bold_font = "DejaVuSans-Bold"
    styles["Normal"].fontName = base_font
    styles["Title"].fontName = bold_font
    styles["Heading3"].fontName = bold_font

    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontName=base_font, fontSize=9))

    story = []

    # === LOGO ZOO PRAHA (nahoře vpravo) ===
    logo = _zoo_logo_flowable(36)  # 36 mm šířka
    if logo:
        story.append(logo)
        story.append(Spacer(1, 6))

    story.append(Paragraph("POUKAZ / ÚČASTNÍCI", styles["Title"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"ID rezervace: <b>{_id}</b>", styles["Normal"]))
    story.append(Paragraph(f"Jméno: <b>{guest_name}</b>", styles["Normal"]))
    story.append(Spacer(1, 8))

    # === (ZDE byla sekce 'Režim datumů' a 'Příjezd/​Odjezd' — odstraněno) ===

    data = [["#", "Jméno", "Zam.", "Nocí", "Pokoj", "Cena (Kč)"]]
    total = 0.0
    for idx, r in parts.iterrows():
        data.append([
            int(r["person_idx"]),
            r["name"],
            "Ano" if int(r["is_employee"]) == 1 else "Ne",
            int(r["nights"]),
            r.get("room_type") or "",
            int(r["price"] or 0),
        ])
        total += float(r["price"] or 0.0)

    tbl = Table(data, colWidths=[8*mm, 55*mm, 12*mm, 14*mm, 35*mm, 25*mm])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), base_font),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
        ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
        ("ALIGN", (0,0), (-1,0), "CENTER"),
        ("ALIGN", (0,1), (0,-1), "CENTER"),
        ("ALIGN", (5,1), (5,-1), "RIGHT"),
        ("FONTNAME", (0,0), (-1,0), bold_font),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
        ("TOPPADDING", (0,0), (-1,0), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>Celkem k úhradě: {int(total)} Kč</b>", styles["Heading3"]))
    story.append(Spacer(1, 4))
    from datetime import datetime as _dt
    story.append(Paragraph(f"Vystaveno: {_dt.now().strftime('%d.%m.%Y %H:%M:%S')}", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()

def fetch_participants(booking_id: str) -> pd.DataFrame:
    with get_conn() as con:
        return pd.read_sql_query("""
            SELECT person_idx, name, is_employee, nights, room_type, price
            FROM participants
            WHERE id = ?
            ORDER BY person_idx
        """, con, params=(booking_id,))

def insert_or_replace_booking(header: dict, rooms_payload: list, overwrite: bool):
    # 1) kontrola konfliktů (kromě self při editaci)
    exclude = header["id"] if overwrite else None
    conflicts = find_room_conflicts(rooms_payload, exclude_id=exclude)
    if conflicts:
        # Sestavíme stručnou zprávu
        sample = conflicts[:5]
        lines = [
            f"- {c['room_type']}: koliduje s {c['existing_id']} ({c['existing_arrival']}–{c['existing_departure']})"
            for c in sample
        ]
        more = f"\n… a další {len(conflicts) - len(sample)} konfliktů." if len(conflicts) > len(sample) else ""
        raise ValueError("Není volno pro vybrané pokoje a termíny:\n" + "\n".join(lines) + more)

    # 2) standardní logika uložení
    with get_conn() as con:
        cur = con.cursor()

        if not overwrite:
            exists = cur.execute("SELECT 1 FROM reservations WHERE id = ?", (header["id"],)).fetchone()
            if exists:
                raise ValueError(f"Rezervace s ID '{header['id']}' už existuje.")

        if overwrite:
            cur.execute("DELETE FROM reservations WHERE id = ?", (header["id"],))
            cur.execute("DELETE FROM reservation_rooms WHERE id = ?", (header["id"],))

        cur.execute("""
            INSERT INTO reservations(id, guest_name, global_arrival, global_departure, global_nights, per_room)
            VALUES(?,?,?,?,?,?)
        """, (
            header["id"],
            header["guest_name"],
            header.get("global_arrival"),
            header.get("global_departure"),
            header.get("global_nights", 0),
            1 if header.get("per_room") else 0
        ))

        for r in rooms_payload:
            cur.execute("""
                INSERT INTO reservation_rooms(id, room_idx, room_type, employees, guests, arrival, departure, nights, price)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                header["id"],
                r["room_idx"],
                r.get("room_type"),
                int(r.get("employees", 0)),
                int(r.get("guests", 0)),
                r.get("arrival"),
                r.get("departure"),
                int(r.get("nights", 0)),
                float(r.get("price", 0.0)),
            ))
        con.commit()
# ---------- CONFIG ----------
def price_for(room_type: str, employees: int, guests: int, nights: int, cfg: pd.DataFrame) -> float:
    if not room_type or nights <= 0:
        return 0.0
    row = cfg[cfg["POKOJ"] == room_type]
    if row.empty:
        return 0.0
    cz = float(row["CENA_Z"].iloc[0])
    cn = float(row["CENA_N"].iloc[0])
    return ((cz * employees) + (cn * guests)) * nights

# ---------- HELPERS ----------
def days_between(a: Optional[date], d: Optional[date]) -> int:
    if not a or not d:
        return 0
    return (d - a).days

def delete_by_id(booking_id: str):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("DELETE FROM reservations WHERE id = ?", (booking_id,))
        cur.execute("DELETE FROM reservation_rooms WHERE id = ?", (booking_id,))
        con.commit()

def insert_booking(payload_header: Dict, payload_rooms: List[Dict]):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO reservations(id, guest_name, global_arrival, global_departure, global_nights, per_room)
            VALUES(?,?,?,?,?,?)
        """, (
            payload_header["id"],
            payload_header["guest_name"],
            payload_header.get("global_arrival"),
            payload_header.get("global_departure"),
            payload_header.get("global_nights", 0),
            1 if payload_header.get("per_room") else 0
        ))
        for r in payload_rooms:
            cur.execute("""
                INSERT INTO reservation_rooms(id, room_idx, room_type, employees, guests, arrival, departure, nights, price)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (
                payload_header["id"],
                r["room_idx"],
                r.get("room_type"),
                r.get("employees", 0),
                r.get("guests", 0),
                r.get("arrival"),
                r.get("departure"),
                r.get("nights", 0),
                r.get("price", 0.0),
            ))
        con.commit()

def fetch_detail(booking_id: str):
    with get_conn() as con:
        cur = con.cursor()
        hdr = cur.execute("SELECT id, guest_name, global_arrival, global_departure, global_nights, per_room FROM reservations WHERE id = ?",
                          (booking_id,)).fetchone()
        rooms = cur.execute("""
            SELECT room_idx, room_type, employees, guests, arrival, departure, nights, price
            FROM reservation_rooms
            WHERE id = ?
            ORDER BY room_idx
        """, (booking_id,)).fetchall()
    return hdr, rooms

def fetch_overview() -> pd.DataFrame:
    with get_conn() as con:
        df = pd.read_sql_query("""
            SELECT r.id AS ID,
                   r.guest_name AS Jmeno,
                   r.global_arrival AS Prijezd,
                   r.global_departure AS Odjezd,
                   r.global_nights AS Noci,
                   CASE r.per_room WHEN 1 THEN 'Per-room' ELSE 'Global' END AS Rezim,
                   CAST(ROUND(COALESCE(SUM(rr.price), 0), 0) AS INTEGER) AS CenaCelkem,
                   COUNT(rr.room_idx) AS PocetPokoju
            FROM reservations r
            LEFT JOIN reservation_rooms rr ON r.id = rr.id
            GROUP BY r.id, r.guest_name, r.global_arrival, r.global_departure, r.global_nights, r.per_room
            ORDER BY r.id DESC
        """, con)
    return df

# ---------- UI ----------
def rooms_form(per_room: bool, cfg: pd.DataFrame,
               global_arrival: Optional[date], global_departure: Optional[date]):
    """Sestaví řádky pokojů a vrátí rooms_payload (list dictů)."""
    st.subheader("Pokoje")
    room_types = [""] + cfg["POKOJ"].tolist()

    rooms_payload = []
    total_price = 0.0

    # hlavičky
    cols_header = st.columns([2,1,1,2,2,1,1]) if per_room else st.columns([2,1,1,1])
    if per_room:
        cols_header[0].markdown("**Typ**")
        cols_header[1].markdown("**Zam.**")
        cols_header[2].markdown("**Hosté**")
        cols_header[3].markdown("**Příjezd**")
        cols_header[4].markdown("**Odjezd**")
        cols_header[5].markdown("**Noci**")
        cols_header[6].markdown("**Cena**")
    else:
        cols_header[0].markdown("**Typ**")
        cols_header[1].markdown("**Zam.**")
        cols_header[2].markdown("**Hosté**")
        cols_header[3].markdown("**Cena**")

    for i in range(1, MAX_ROOMS + 1):
        with st.container():
            if per_room:
                c1, c2, c3, c4, c5, c6, c7 = st.columns([2,1,1,2,2,1,1])

                rt = c1.selectbox(f"Typ {i}", room_types, key=f"rt_{i}", label_visibility="collapsed")
                em = c2.number_input("Zam.", min_value=0, step=1, key=f"em_{i}", label_visibility="collapsed")
                gu = c3.number_input("Hosté", min_value=0, step=1, key=f"gu_{i}", label_visibility="collapsed")

                # defaulty per-room datumů ze session_state (nezávislé na globálu)
                arr_default = st.session_state.get(f"arr_{i}", date.today())
                dep_default = st.session_state.get(f"dep_{i}", date.today())
                arr = c4.date_input(f"Arr {i}", value=arr_default, key=f"arr_{i}",
                                    format="DD.MM.YYYY", label_visibility="collapsed")
                dep = c5.date_input(f"Dep {i}", value=dep_default, key=f"dep_{i}",
                                    format="DD.MM.YYYY", label_visibility="collapsed")

                nights = max(0, days_between(arr, dep))
                c6.write(nights)

                pr = price_for(rt, int(em), int(gu), nights, cfg)
                c7.write(int(pr))

                if rt:
                    rooms_payload.append({
                        "room_idx": i,
                        "room_type": rt,
                        "employees": int(em),
                        "guests": int(gu),
                        "arrival": arr.strftime("%d.%m.%Y"),
                        "departure": dep.strftime("%d.%m.%Y"),
                        "nights": nights,
                        "price": pr
                    })
                    total_price += pr

            else:
                c1, c2, c3, c4 = st.columns([2,1,1,1])
                rt = c1.selectbox(f"Typ {i}", room_types, key=f"rt_{i}", label_visibility="collapsed")
                em = c2.number_input("Zam.", min_value=0, step=1, key=f"em_{i}", label_visibility="collapsed")
                gu = c3.number_input("Hosté", min_value=0, step=1, key=f"gu_{i}", label_visibility="collapsed")

                nights = max(0, days_between(global_arrival, global_departure))
                pr = price_for(rt, int(em), int(gu), nights, cfg)
                c4.write(int(pr))

                if rt:
                    rooms_payload.append({
                        "room_idx": i,
                        "room_type": rt,
                        "employees": int(em),
                        "guests": int(gu),
                        "arrival": global_arrival.strftime("%d.%m.%Y") if global_arrival else "",
                        "departure": global_departure.strftime("%d.%m.%Y") if global_departure else "",
                        "nights": nights,
                        "price": pr
                    })
                    total_price += pr

    st.markdown(f"**Cena celkem:** {int(total_price)} Kč")
    return rooms_payload



# --- KOL. SMLOUVA (jednotné jméno a cesty) ---
KS_BASENAME = "KS_2024-25.pdf"                  # <— sem dáš správný soubor
KS_PATH = Path("static") / KS_BASENAME

def ks_exists() -> bool:
    try:
        return KS_PATH.exists() and KS_PATH.stat().st_size > 0
    except Exception:
        return False

def ks_url() -> str:
    # relativní URL funguje i za reverzní proxy (/hejnice/)
    return f"./static/{KS_BASENAME}"


import pandas as pd

def fetch_overview_rooms() -> pd.DataFrame:
    with get_conn() as con:
        df = pd.read_sql_query("""
            SELECT 
                r.id                    AS ID,
                r.guest_name            AS Jmeno,
                rr.room_idx             AS PokojIndex,
                rr.room_type            AS Pokoj,
                rr.employees            AS Zamestnanci,
                rr.guests               AS Hoste,
                CASE WHEN r.per_room = 1 THEN rr.arrival  ELSE r.global_arrival  END AS Prijezd,
                CASE WHEN r.per_room = 1 THEN rr.departure ELSE r.global_departure END AS Odjezd,
                CASE WHEN r.per_room = 1 THEN rr.nights    ELSE r.global_nights   END AS Noci,
                CAST(ROUND(rr.price, 0) AS INTEGER) AS Cena
            FROM reservations r
            JOIN reservation_rooms rr ON r.id = rr.id
            ORDER BY r.id DESC, rr.room_idx
        """, con)
    return df


# --- KALENDÁŘ: pomocné funkce (bez kapacity) ---
import calendar
from datetime import datetime as dt

def _parse_cz_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return dt.strptime(s, "%d.%m.%Y").date()
    except Exception:
        return None

def occupancy_by_day_boolean() -> pd.DataFrame:
    with get_conn() as con:
        rows = pd.read_sql_query("""
            SELECT room_type, arrival, departure
            FROM reservation_rooms
            WHERE room_type IS NOT NULL AND room_type <> ''
        """, con)

    if rows.empty:
        return pd.DataFrame(columns=["date", "room_type", "occupied"])

    recs = []
    for _, r in rows.iterrows():
        rt = str(r["room_type"])
        a = _parse_cz_date(str(r["arrival"]))
        d = _parse_cz_date(str(r["departure"]))
        if not a or not d:
            continue
        curr = a
        while curr < d:  # odjezd exkluzivně
            recs.append({"date": curr, "room_type": rt, "occupied": 1})
            curr = curr + timedelta(days=1)   # ✅ čistý posun o den

    if not recs:
        return pd.DataFrame(columns=["date", "room_type", "occupied"])

    df = pd.DataFrame(recs)
    df = df.groupby(["date", "room_type"], as_index=False)["occupied"].max()
    return df

def availability_for_month_bool(room_type: str, year: int, month: int) -> pd.DataFrame:
    """
    ['date','available']  (True = volno, False = obsazeno) pro daný typ pokoje.
    """
    occ = occupancy_by_day_boolean()
    occ_rt = occ[occ["room_type"] == room_type] if not occ.empty else pd.DataFrame(columns=["date","occupied"])

    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    days = pd.date_range(first, date(year, month, last_day), freq="D").date

    merged = pd.DataFrame({"date": days}).merge(occ_rt[["date","occupied"]], on="date", how="left")
    merged["occupied"] = merged["occupied"].fillna(0).astype(int)
    merged["available"] = merged["occupied"].apply(lambda x: False if x >= 1 else True)
    return merged[["date", "available"]]
def render_calendar_matrix_bool(av_df: pd.DataFrame, year: int, month: int, title: str = ""):
    """
    Mini kalendář Po–Ne:
      🟢 volno (available=True), 🔴 plno (available=False)
    """
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    weeks = cal.monthdayscalendar(year, month)  # 0 = prázdná buňka

    avail_map = {row["date"]: bool(row["available"]) for _, row in av_df.iterrows()}

    if title:
        st.markdown(f"**{title}**")

    # hlavička dní
    head = st.columns(7)
    for i, wd in enumerate(["Po","Út","St","Čt","Pá","So","Ne"]):
        head[i].markdown(f"<div style='text-align:center'><strong>{wd}</strong></div>", unsafe_allow_html=True)

    # týdny
    for wk in weeks:
        cols = st.columns(7)
        for i, d in enumerate(wk):
            if d == 0:
                cols[i].markdown("&nbsp;", unsafe_allow_html=True)
            else:
                the_date = date(year, month, d)
                available = avail_map.get(the_date, True)  # default volno
                dot = "🟢" if available else "🔴"
                cols[i].markdown(f"<div style='text-align:center'>{dot} <strong>{d:02d}</strong></div>", unsafe_allow_html=True)

def calendars_all_ui():
    st.header("Kalendář obsazenosti – všechny typy pokojů")
    cfg = get_cfg()
    room_types = cfg["POKOJ"].tolist()
    if not room_types:
        st.warning("V config_Hejnice.csv nejsou žádné typy pokojů.")
        return

    today = date.today()
    c1, c2 = st.columns(2)
    year = c1.number_input("Rok", min_value=2000, max_value=2100, value=today.year, step=1)
    month = c2.number_input("Měsíc", min_value=1, max_value=12, value=today.month, step=1)

    # vykreslíme kalendáře pro všechny typy, po dvou vedle sebe
    cols_per_row = 2
    for i, rt in enumerate(room_types):
        if i % cols_per_row == 0:
            row = st.columns(cols_per_row)
        av = availability_for_month_bool(rt, int(year), int(month))
        with row[i % cols_per_row]:
            st.markdown(f"### {rt}")
            render_calendar_matrix_bool(av, int(year), int(month))
            st.markdown("---")


import json

def create_reservation_from_request(req_id: str) -> str:
    """
    Vezme žádost z `requests` (vč. rooms_json, per_room) a vytvoří plnohodnotnou
    rezervaci v `reservations` + `reservation_rooms`. Vrací booking_id.
    """
    with get_conn() as con:
        row = con.execute("""
            SELECT req_id, guest_name, contact, arrival, departure, nights, people,
                   note, status, COALESCE(per_room,0) AS per_room, rooms_json
            FROM requests WHERE req_id = ?
        """, (req_id,)).fetchone()

    if not row:
        raise ValueError("Žádost nenalezena.")

    (_req_id, guest_name, contact, arr, dep, nights, people,
     note, status, per_room_flag, rooms_json) = row

    per_room = int(per_room_flag) == 1
    if not rooms_json:
        raise ValueError("V žádosti chybí rooms_json (detail pokojů).")

    try:
        rooms = json.loads(rooms_json)
    except Exception as e:
        raise ValueError(f"Neplatný JSON v žádosti: {e}")

    # Header rezervace
    booking_id = new_booking_id()
    header = {
        "id": booking_id,
        "guest_name": guest_name or "",
        "global_arrival": arr if not per_room else None,
        "global_departure": dep if not per_room else None,
        "global_nights": (int(nights or 0) if not per_room else 0),
        "per_room": per_room,
    }

    # Pokoje + ceny z ceníku
    cfg = get_cfg()
    rooms_payload = []
    for idx, r in enumerate(rooms, start=1):
        rt = r.get("room_type") or ""
        em = int(r.get("employees", 0))
        gu = int(r.get("guests", 0))
        a  = r.get("arrival") or ""
        d  = r.get("departure") or ""
        n  = int(r.get("nights", 0))
        price = float(price_for(rt, em, gu, n, cfg))
        rooms_payload.append({
            "room_idx": idx,
            "room_type": rt,
            "employees": em,
            "guests": gu,
            "arrival": a,
            "departure": d,
            "nights": n,
            "price": price,
        })

    # Uložení (kontrola kolizí je uvnitř insert_or_replace_booking)
    insert_or_replace_booking(header, rooms_payload, overwrite=False)

    # volitelně: označ žádost jako vyřízenou
    update_request_status(req_id, "vyřízeno")

    return booking_id

import pandas as pd
from datetime import date

def shade_weekend_columns(df, year: int, month: int, room_col: str = "Pokoj", color: str = "#f3f4f6"):
    """
    Obarví sloupce (SO/NE) v měsíční mřížce: první sloupec je názvy pokojů,
    ostatní jsou dny 1..31. Vrací pandas Styler.
    """
    # připrav mapování day->is_weekend
    cal = _cal.Calendar(firstweekday=0)  # 0=pondělí vlevo
    weekend_days = set()
    for d in cal.itermonthdates(year, month):
        if d.month == month and d.weekday() >= 5:  # 5=SO, 6=NE
            weekend_days.add(d.day)

    # připrav stylovací mřížku (stejně velká jako df)
    styles = pd.DataFrame("", index=df.index, columns=df.columns)

    # obarvi víkendové sloupce (ignoruj první sloupec s názvy pokojů)
    for col in df.columns:
        if col == room_col:
            continue
        # sloupce mohou být int i str → normalizace
        try:
            day_num = int(col)
        except (ValueError, TypeError):
            continue
        if day_num in weekend_days:
            styles[col] = f"background-color: {color}"

    return df.style.apply(lambda _: styles, axis=None)

# --- KALENDÁŘ: pomocné funkce (bez kapacity, boolean obsazenosti) ---
import calendar
from datetime import datetime as dt, timedelta

def _parse_cz_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return dt.strptime(s, "%d.%m.%Y").date()
    except Exception:
        return None

def occupancy_by_day_boolean() -> pd.DataFrame:
    """
    ['date','room_type','occupied'] kde occupied ∈ {0,1}.
    Příjezd včetně, odjezd exkluzivně.
    """
    with get_conn() as con:
        rows = pd.read_sql_query("""
            SELECT room_type, arrival, departure
            FROM reservation_rooms
            WHERE room_type IS NOT NULL AND room_type <> ''
        """, con)

    if rows.empty:
        return pd.DataFrame(columns=["date", "room_type", "occupied"])

    recs = []
    for _, r in rows.iterrows():
        rt = str(r["room_type"])
        a = _parse_cz_date(str(r["arrival"]))
        d = _parse_cz_date(str(r["departure"]))
        if not a or not d:
            continue
        curr = a
        while curr < d:  # odjezd exkluzivně
            recs.append({"date": curr, "room_type": rt, "occupied": 1})
            curr = curr + timedelta(days=1)

    if not recs:
        return pd.DataFrame(columns=["date", "room_type", "occupied"])

    df = pd.DataFrame(recs)
    # aspoň jedna rezervace daného typu a dne => obsazeno (1)
    df = df.groupby(["date", "room_type"], as_index=False)["occupied"].max()
    return df


from datetime import date
from typing import Optional


def calendar_matrix_ui():
    st.header("Měsíční kalendář obsazenosti (tabulka)")

    today = date.today()
    year = st.number_input("Rok", min_value=2000, max_value=2100, value=today.year, step=1)
    month = st.number_input("Měsíc", min_value=1, max_value=12, value=today.month, step=1)

    df = availability_matrix(year, month)

    if df.empty:
        st.warning("Žádná data.")
        return

    # víkendy šedě
    styled = shade_weekend_columns(df, year, month, room_col="Pokoj", color="#f3f4f6")

    st.dataframe(styled, use_container_width=True)


def booking_form(edit_id: Optional[str] = None):
    # >>> PŘEDVYPLNĚNÍ Z VEŘEJNÉ ŽÁDOSTI (rooms_json -> stejné UI) <<<
    pending = st.session_state.get("pending_order")
    if pending and not edit_id:
        # režim
        per_room_from_req = bool(pending.get("per_room", False))
        st.session_state["per_room_mode"] = per_room_from_req

        # žadatel
        st.session_state["guest_name_prefill"] = pending.get("guest_name", "")

        # globální datumy (jen když žádost nebyla per-room)
        from datetime import datetime as _dt
        def _p(s):
            try:
                return _dt.strptime(str(s), "%d.%m.%Y").date() if s else None
            except Exception:
                return None

        if not per_room_from_req:
            ga = _p(pending.get("global_arrival"))
            gd = _p(pending.get("global_departure"))
            if ga: st.session_state["global_arrival_tmp"] = ga
            if gd: st.session_state["global_departure_tmp"] = gd

        # pokoje
        rooms = pending.get("rooms", []) or []
        for i, r in enumerate(rooms, start=1):
            st.session_state[f"rt_{i}"] = r.get("room_type", "")
            st.session_state[f"em_{i}"] = int(r.get("employees", 0))
            st.session_state[f"gu_{i}"] = int(r.get("guests", 0))
            ai = _p(r.get("arrival"))
            di = _p(r.get("departure"))
            if ai: st.session_state[f"arr_{i}"] = ai
            if di: st.session_state[f"dep_{i}"] = di

        # jednorázové použití
        st.session_state["pending_order"] = None


    cfg = get_cfg()
    st.header("Rezervace")

    # ===== per-room přepínač MIMO form (okamžitý rerender) =====
    if "per_room_mode" not in st.session_state:
        st.session_state["per_room_mode"] = False
    prev_mode = st.session_state["per_room_mode"]

    per_room = st.checkbox("Vlastní datumy pro každý pokoj (per-room)",
                           value=prev_mode, key="per_room_mode")

    # jednorázové zkopírování globálních dat do per-room při přepnutí
    if per_room != prev_mode:
        if per_room and "global_arrival_tmp" in st.session_state and "global_departure_tmp" in st.session_state:
            for i in range(1, MAX_ROOMS + 1):
                st.session_state[f"arr_{i}"] = st.session_state["global_arrival_tmp"]
                st.session_state[f"dep_{i}"] = st.session_state["global_departure_tmp"]
        st.rerun()

    # ===== globální datumy (jen když není per-room) =====
    if not per_room:
        cga, cgd = st.columns(2)
        global_arrival = cga.date_input("Příjezd", value=date.today(),
                                        format="DD.MM.YYYY", key="global_arrival_tmp")
        global_departure = cgd.date_input("Odjezd", value=date.today(),
                                          format="DD.MM.YYYY", key="global_departure_tmp")
        global_nights = max(0, days_between(global_arrival, global_departure))
        st.write(f"Nocí: **{global_nights}**")
    else:
        global_arrival = None
        global_departure = None
        global_nights = 0

    # ===== FORM =====
    with st.form("booking_form"):
        # Základní údaje
        c1, c2 = st.columns(2)
        guest_name = c1.text_input("Jméno a příjmení",
                                   value=st.session_state.get("guest_name_prefill", ""))

        # ID – u editace fixní, u nového jen informace
        if edit_id:
            c2.text_input("ID rezervace", value=edit_id, disabled=True,
                          help="ID nelze měnit v režimu úprav.")
        else:
            c2.text_input("ID rezervace", value="(bude přiděleno při uložení)", disabled=True)

        # Pokoje + ceny (živý přepočet)
        rooms_payload = rooms_form(per_room, cfg, global_arrival, global_departure)

        st.markdown("---")
        save_clicked = st.form_submit_button("Vložit rezervaci")

    # ===== Uložení =====
    if not save_clicked:
        return

    overwrite = bool(edit_id)

    # základní validace
    if not guest_name.strip():
        st.error("Vyplň jméno.")
        return
    if len(rooms_payload) == 0:
        st.error("Vyber aspoň jeden pokoj (vyplň typ).")
        return

    # validace datumů/nocí (globální i per-room)
    ok, msg = validate_dates_and_nights(per_room, global_arrival, global_departure, rooms_payload)
    if not ok:
        st.error(msg)
        return

    # ID – nové jen při vytvoření
    booking_id = edit_id or new_booking_id()

    header = {
        "id": booking_id.strip(),
        "guest_name": guest_name.strip(),
        "global_arrival": global_arrival.strftime("%d.%m.%Y") if global_arrival else None,
        "global_departure": global_departure.strftime("%d.%m.%Y") if global_departure else None,
        "global_nights": (max(0, days_between(global_arrival, global_departure)) if not per_room else 0),
        "per_room": per_room
    }

    try:
        insert_or_replace_booking(header, rooms_payload, overwrite=overwrite)
        st.success(f"Rezervace uložena. ID: {booking_id}")
    except ValueError as e:
        # např. kolize pokojů (find_room_conflicts)
        st.error(str(e))
    except Exception as e:
        st.error(f"Uložení selhalo: {e}")


def edit_by_id_ui():
    st.header("Upravit rezervaci podle ID")
    target = st.text_input("Zadej ID:", key="edit_id")
    if st.button("Načíst"):
        if not target.strip():
            st.error("Zadej ID.")
            return
        hdr, rooms = fetch_detail(target.strip())
        if not hdr:
            st.error("ID nenalezeno.")
            return
        # Prefill session state pro formulář
        _, guest_name, garr, gdep, gnights, per_room = hdr
        st.session_state.clear()
        # předvyplň pole
        st.session_state["Jméno a příjmení"] = guest_name
        st.session_state["ID rezervace"] = target.strip()
        if per_room == 1:
            st.session_state["Vlastní datumy pro každý pokoj (per-room)"] = True
        # pokoje
        for r in rooms:
            room_idx, room_type, employees, guests, arr, dep, nights, price = r
            st.session_state[f"rt_{room_idx}"] = room_type or ""
            st.session_state[f"em_{room_idx}"] = int(employees or 0)
            st.session_state[f"gu_{room_idx}"] = int(guests or 0)
            if per_room == 1:
                # Streamlit očekává date, přeparsujeme
                try:
                    d, m, y = [int(p) for p in (arr or "01.01.1970").split(".")]
                    st.session_state[f"arr_{room_idx}"] = date(y, m, d)
                    d, m, y = [int(p) for p in (dep or "01.01.1970").split(".")]
                    st.session_state[f"dep_{room_idx}"] = date(y, m, d)
                except Exception:
                    pass
        st.info("Níže otevři formulář Rezervace, hodnoty jsou předvyplněné. Po Uložit se původní záznamy přepíšou.")


from typing import Tuple

def validate_dates_and_nights(per_room: bool,
                              global_arrival: Optional[date],
                              global_departure: Optional[date],
                              rooms_payload: list[dict]) -> Tuple[bool, str]:
    """
    Vrací (ok, message). Validuje, že počet nocí je vždy >= 1.
    - Globální režim: kontroluje globální A/D.
    - Per-room: kontroluje A/D na každém vyplněném pokoji.
    """
    # Globální režim
    if not per_room:
        if not global_arrival or not global_departure:
            return False, "Zadej globální příjezd i odjezd."
        n = days_between(global_arrival, global_departure)
        if n <= 0:
            return False, "Globální odjezd musí být později než příjezd (minimálně 1 noc)."
        return True, ""

    # Per-room režim
    errors = []
    for r in rooms_payload:
        rt = (r.get("room_type") or "").strip()
        if not rt:
            # prázdný řádek ignorujeme – do DB se stejně neukládá
            continue
        a_s = r.get("arrival") or ""
        d_s = r.get("departure") or ""
        a = _parse_cz_date(a_s)
        d = _parse_cz_date(d_s)
        if not a or not d:
            errors.append(f"Pokoj '{rt}': chybí/špatné datumy (příjezd/odjezd).")
            continue
        n = (d - a).days
        if n <= 0:
            errors.append(f"Pokoj '{rt}': odjezd musí být po příjezdu (min. 1 noc).")
    if errors:
        return False, "Nelze uložit:\n- " + "\n- ".join(errors)
    return True, ""

def overview_ui():
    st.header("Přehled rezervací")

    mode = st.radio("Zobrazení", ["Souhrn (1 řádek na rezervaci)", "Po pokojích (1 řádek na pokoj)"], index=0)

    if mode.startswith("Souhrn"):
        df = fetch_overview()
    else:
        df = fetch_overview_rooms()

    # Vynutit celé hodnoty (obrana i kdyby SQL někde vrátilo float)
    if "CenaCelkem" in df.columns:
        df["CenaCelkem"] = pd.to_numeric(df["CenaCelkem"], errors="coerce").round(0).astype("Int64")
    if "Cena" in df.columns:
        df["Cena"] = pd.to_numeric(df["Cena"], errors="coerce").round(0).astype("Int64")

    # Tady NEMA smysl víkendové stínování – to je pro měsíční mřížku.
    # Prosté vykreslení s column_config:
    colcfg = {}
    if "CenaCelkem" in df.columns:
        colcfg["CenaCelkem"] = st.column_config.NumberColumn(format="%d")
    if "Cena" in df.columns:
        colcfg["Cena"] = st.column_config.NumberColumn(format="%d")
    if "Noci" in df.columns:
        colcfg["Noci"] = st.column_config.NumberColumn(format="%d")
    if "PocetPokoju" in df.columns:
        colcfg["PocetPokoju"] = st.column_config.NumberColumn(format="%d")
    if "Zamestnanci" in df.columns:
        colcfg["Zamestnanci"] = st.column_config.NumberColumn(format="%d")
    if "Hoste" in df.columns:
        colcfg["Hoste"] = st.column_config.NumberColumn(format="%d")
    if "PokojIndex" in df.columns:
        colcfg["PokojIndex"] = st.column_config.NumberColumn(format="%d")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config=colcfg
    )

from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as PLImage
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from pathlib import Path
from reportlab.lib.units import mm

def _zoo_logo_flowable(max_width_mm: float = 36):
    """
    Vrátí flowable s logem ZOO Praha zarovnaným doprava (nebo None, když není k dispozici).
    Očekává soubor ./static/zoo_logo.png
    """
    try:
        p = Path("static/zoo_logo.png")
        if not p.exists() or p.stat().st_size == 0:
            return None
        # zachovej poměr stran
        ir = ImageReader(str(p))
        iw, ih = ir.getSize()
        aspect = (ih / float(iw)) if iw else 1.0

        img = PLImage(str(p))
        img.drawWidth = max_width_mm * mm
        img.drawHeight = (max_width_mm * mm) * aspect
        img.hAlign = "RIGHT"
        return img
    except Exception:
        return None

def create_voucher_pdf_bytes(booking_id: str) -> bytes:
    # unicode fonty (beze změny)...
    ensure_czech_fonts()

    hdr, rooms = fetch_detail(booking_id)
    if not hdr:
        raise ValueError("ID nenalezeno.")
    _id, guest_name, garr, gdep, gnights, per_room = hdr

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()

    # Fonty – počítáme s tím, že ensure_czech_fonts už proběhlo
    base_font = "DejaVuSans"
    bold_font = "DejaVuSans-Bold"


    styles["Normal"].fontName = base_font
    styles["Title"].fontName = bold_font
    styles["Heading3"].fontName = bold_font
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontName=base_font, fontSize=9))

    story = []

    # === LOGO ZOO PRAHA (nahoře vpravo) ===
    logo = _zoo_logo_flowable(36)
    if logo:
        story.append(logo)
        story.append(Spacer(1, 6))

    story.append(Paragraph("POUKAZ / REZERVACE", styles["Title"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"ID rezervace: <b>{_id}</b>", styles["Normal"]))
    story.append(Paragraph(f"Jméno: <b>{guest_name}</b>", styles["Normal"]))
    story.append(Spacer(1, 8))

    # === (ZDE byla sekce 'Režim datumů' a 'Příjezd/​Odjezd' — odstraněno) ===

    data = [["#", "Pokoj", "Zam.", "Hosté", "Příjezd", "Odjezd", "Nocí", "Cena (Kč)"]]
    total = 0.0
    for idx, r in enumerate(rooms, start=1):
        room_idx, room_type, employees, guests, arr, dep, nights, price = r
        total += float(price or 0.0)
        a, d, n = (arr or garr or ""), (dep or gdep or ""), (nights or gnights or 0)
        data.append([idx, room_type or "", int(employees or 0), int(guests or 0), a, d, int(n), int(price or 0)])

    tbl = Table(data, colWidths=[8*mm, 35*mm, 14*mm, 16*mm, 24*mm, 24*mm, 12*mm, 24*mm])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), base_font),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
        ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
        ("ALIGN", (0,0), (-1,0), "CENTER"),
        ("ALIGN", (0,1), (0,-1), "CENTER"),
        ("ALIGN", (6,1), (7,-1), "RIGHT"),
        ("FONTNAME", (0,0), (-1,0), bold_font),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
        ("TOPPADDING", (0,0), (-1,0), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>Celkem k úhradě: {int(total)} Kč</b>", styles["Heading3"]))
    story.append(Spacer(1, 4))
    from datetime import datetime as _dt
    story.append(Paragraph(f"Vystaveno: {_dt.now().strftime('%d.%m.%Y %H:%M:%S')}", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()

def counter(col, key: str, label: str = "", min_value: int = 0) -> int:
    # inicializace
    if key not in st.session_state:
        st.session_state[key] = 0

    b_minus, b_val, b_plus = col.columns([1, 2, 1])

    # „–“ tlačítko
    if b_minus.button("−", key=f"{key}_dec"):
        st.session_state[key] = max(min_value, int(st.session_state[key]) - 1)
        st.rerun()

    # zobrazení + možnost přepsat ručně (nezávislý key, aby se nehádal s tlačítky)
    v = b_val.number_input(
        label or key, min_value=min_value, step=1,
        value=int(st.session_state[key]), key=f"{key}_num", label_visibility="collapsed"
    )
    if int(v) != st.session_state[key]:
        st.session_state[key] = int(v)

    # „+“ tlačítko
    if b_plus.button("+", key=f"{key}_inc"):
        st.session_state[key] = int(st.session_state[key]) + 1
        st.rerun()

    return int(st.session_state[key])




def voucher_ui():
    st.header("Vygenerovat poukaz (PDF)")
    with get_conn() as con:
        rows = con.execute("SELECT id, guest_name FROM reservations ORDER BY id DESC").fetchall()
    if not rows:
        st.info("Zatím nejsou žádné rezervace.")
        return


    options = [f"{r[0]} — {r[1]}" for r in rows]
    label_to_id = {opt: rows[i][0] for i, opt in enumerate(options)}

    c1, c2 = st.columns([2,1])
    chosen_label = c1.selectbox("Vyber rezervaci", options, key="voucher_select")
    gen_clicked = c2.button("Vytvořit PDF", key="voucher_gen_btn")
    # --- náhled (komínek – cena) pro vybranou rezervaci ---
    if chosen_label:
        booking_id = label_to_id[chosen_label]
        hdr, rooms = fetch_detail(booking_id)
        if hdr:
            _id, guest_name, garr, gdep, gnights, per_room = hdr

            st.markdown("**Komínek – cena**")
            data = []
            total = 0.0
            for r in rooms:
                room_idx, room_type, employees, guests, arr, dep, nights, price = r
                total += float(price or 0.0)
                a = arr or garr or ""
                d = dep or gdep or ""
                n = int(nights or gnights or 0)
                data.append({
                    "Pokoj #": int(room_idx),
                    "Typ": room_type or "",
                    "Zam.": int(employees or 0),
                    "Hosté": int(guests or 0),
                    "Příjezd": a,
                    "Odjezd": d,
                    "Nocí": n,
                    "Cena (Kč)": int(price or 0),
                })

            import pandas as pd
            df_display = pd.DataFrame(data)

            # zobraz cenu jako celé číslo
            if "Cena (Kč)" in df_display.columns:
                df_display["Cena (Kč)"] = df_display["Cena (Kč)"].astype("Int64")

            st.dataframe(
                df_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Cena (Kč)": st.column_config.NumberColumn(format="%d")  # bez desetinných míst
                }
            )
            st.markdown(f"**Celkem:** {int(total)} Kč")
            st.markdown("---")

    # přednačti příjemce
    recipient, mcfg = get_mail_recipient()
    st.caption(f"Adresát e-mailu: **{recipient or 'nenalezen'}** (configMAIL.csv)")

    # cache PDF v session
    if gen_clicked:
        booking_id = label_to_id[chosen_label]
        try:
            pdf_bytes = create_voucher_pdf_bytes(booking_id)
            st.session_state["voucher_pdf_bytes"] = pdf_bytes
            st.session_state["voucher_pdf_name"] = f"poukaz_{booking_id}.pdf"
            st.success("Poukaz vygenerován.")
            st.download_button(
                label="Stáhnout poukaz PDF",
                data=pdf_bytes,
                file_name=st.session_state["voucher_pdf_name"],
                mime="application/pdf",
            )
        except Exception as e:
            st.error(f"Nepodařilo se vygenerovat poukaz: {e}")

    colA, colB = st.columns([1,1])
    send_clicked = colA.button("Odeslat e-mailem", type="primary", key="voucher_send_btn")

    if send_clicked:
        if not recipient:
            st.error("Nelze odeslat: chybí e-mail v configMAIL.csv.")
            return

        booking_id = label_to_id[chosen_label]
        pdf_bytes = st.session_state.get("voucher_pdf_bytes")
        pdf_name  = st.session_state.get("voucher_pdf_name") or f"poukaz_{booking_id}.pdf"
        if not pdf_bytes:
            try:
                pdf_bytes = create_voucher_pdf_bytes(booking_id)
            except Exception as e:
                st.error(f"PDF se nepodařilo vytvořit: {e}")
                return

        try:
            subj = mcfg.get("SUBJECT_VOUCHER") or f"Poukaz k rezervaci {booking_id}"
            body = mcfg.get("BODY_VOUCHER") or "Dobrý den,\n\nv příloze zasíláme poukaz k rezervaci.\n\nS pozdravem\nHejnice/Dobřejov"
            send_email_with_attachment(recipient, subj, body, pdf_bytes, pdf_name)
            st.success(f"E-mail odeslán na {recipient}.")
        except Exception as e:
            st.error(f"Odeslání e-mailu selhalo: {e}")


def sidebar_site_badge():
    site = st.session_state.get("site")
    if site:
        st.sidebar.success(f"Aktivní: **{site}**")
        role = current_role()
        if role == "admin":
            st.sidebar.info("Role: **Admin**")
            # Mail badge
            try:
                mail, _mcfg = get_mail_recipient()
                if mail:
                    st.sidebar.success(f"E-mail příjemce: {mail}")
                else:
                    st.sidebar.warning("E-mail příjemce nenalezen (configMAIL.csv).")
            except Exception:
                pass
        elif role == "dohled":
            st.sidebar.info("Role: **Dohled**")
        else:
            st.sidebar.info("Role: **Zaměstnanec**")

        if st.sidebar.button("Změnit lokalitu", key="change_site"):
            # uchovej roli při změně lokality
            role = st.session_state.get("role", "public")
            st.session_state.clear()
            st.session_state["role"] = role
            # po kliknutí přesměruj do výběru lokality
            if "site" in st.session_state:
                del st.session_state["site"]
            st.rerun()

        if role != "public" and st.sidebar.button("Odhlásit roli", key="logout_role"):
            logout_role()
            st.rerun()

    else:
        st.sidebar.warning("Nevybraná lokalita")


def availability_matrix(year: int, month: int) -> pd.DataFrame:
    """
    Vrátí DataFrame: řádky = pokoje, sloupce = dny v měsíci,
    hodnoty = True (volno) / False (obsazeno).
    """
    cfg = get_cfg()
    room_types = cfg["POKOJ"].tolist()
    if not room_types:
        return pd.DataFrame()

    last_day = calendar.monthrange(year, month)[1]
    days = [date(year, month, d) for d in range(1, last_day + 1)]

    occ = occupancy_by_day_boolean()

    data = {}
    for rt in room_types:
        row = []
        for d in days:
            occupied = False
            if not occ.empty:
                mask = (occ["room_type"] == rt) & (occ["date"] == d) & (occ["occupied"] == 1)
                if not occ[mask].empty:
                    occupied = True
            row.append(not occupied)  # True = volno, False = obsazeno
        data[rt] = row

    df = pd.DataFrame(data, index=days).T
    df.columns = [d.day for d in days]
    return df

def render_availability_grid(year: int, month: int, show_names: bool = False):
    df = availability_matrix(year, month)
    if df.empty:
        st.warning("Žádné pokoje v configu nebo prázdná data.")
        return

    # jména do buněk jen pro admina
    name_map = {}
    if show_names:
        name_map = occupied_name_map()  # {(room_type, date) -> "Jméno (ID)"}

    # sloupce = 1..last_day
    last_day = calendar.monthrange(year, month)[1]

    # CSS: čitelný kontrast pro text v buňkách
    cell_css = "border:1px solid #ccc;padding:6px;text-align:center;font-size:11px;line-height:1.05;"
    html = "<table style='border-collapse:collapse;width:100%;font-size:13px;'>"

    # hlavička
    html += "<tr><th style='border:1px solid #ccc;padding:4px 2px;text-align:left;'>Pokoj</th>"
    for d in range(1, last_day + 1):
        html += f"<th style='border:1px solid #ccc;padding:2px;text-align:center;width:28px'>{d}</th>"
    html += "</tr>"

    # řádky
    for room, row in df.iterrows():
        html += f"<tr><td style='border:1px solid #ccc;padding:4px 6px;text-align:left;font-weight:bold;white-space:nowrap'>{room}</td>"
        for d in range(1, last_day + 1):
            val = bool(row.get(d, True))  # True = volno, False = obsazeno
            day_date = date(year, month, d)
            if val:
                # volno – prázdné pole (zelené)
                html += f"<td style='{cell_css}background:#2ecc71;color:#0b3d0b' title='Volno'></td>"
            else:
                # obsazeno – červené + jméno/tooltip (pokud admin)
                label = ""
                title = "Obsazeno"
                if show_names:
                    nm = name_map.get((room, day_date))
                    if nm:
                        title = nm
                        # zkrátit do buňky, ať se nerozbije layout
                        label = nm if len(nm) <= 12 else nm[:12] + "…"
                html += f"<td style='{cell_css}background:#e74c3c;color:#fff' title='{title}'>{label}</td>"
        html += "</tr>"
    html += "</table>"

    st.markdown(html, unsafe_allow_html=True)



def _ranges_overlap(a1, d1, a2, d2) -> bool:
    """Interval je [a, d) – odjezd exkluzivně. Vrací True, když se překrývá."""
    return not (d1 <= a2 or d2 <= a1)

def find_room_conflicts(rooms_payload: list[dict], exclude_id: Optional[str] = None) -> list[dict]:
    """
    Zjistí konflikty v DB vůči plánovaným řádkům pokojů.
    rooms_payload: položky s klíči room_type, arrival (dd.mm.yyyy), departure (dd.mm.yyyy)
    exclude_id: ID, které při kontrole ignorujeme (při editaci).
    Vrací list dictů: {room_type, existing_id, existing_arrival, existing_departure, new_arrival, new_departure}
    """
    conflicts = []
    with get_conn() as con:
        cur = con.cursor()
        for r in rooms_payload:
            rt = (r.get("room_type") or "").strip()
            a = _parse_cz_date(r.get("arrival") or "")
            d = _parse_cz_date(r.get("departure") or "")
            if not rt or not a or not d or a >= d:
                # prázdné/nesmyslné řádky přeskočíme (neumožní uložit jinde)
                continue

            params = [rt]
            sql = "SELECT id, arrival, departure FROM reservation_rooms WHERE room_type = ?"
            if exclude_id:
                sql += " AND id <> ?"
                params.append(exclude_id)

            for (eid, ea_s, ed_s) in cur.execute(sql, params).fetchall():
                ea = _parse_cz_date(ea_s or "")
                ed = _parse_cz_date(ed_s or "")
                if not ea or not ed:
                    continue
                if _ranges_overlap(a, d, ea, ed):
                    conflicts.append({
                        "room_type": rt,
                        "existing_id": eid,
                        "existing_arrival": ea_s,
                        "existing_departure": ed_s,
                        "new_arrival": r.get("arrival"),
                        "new_departure": r.get("departure"),
                    })
    return conflicts


def calendar_year_ui():
    today = date.today()
    year = st.number_input("Rok", min_value=2000, max_value=2100, value=today.year, step=1)

    st.header(f"Kalendář obsazenosti – {int(year)} (celý rok)")

    for month in range(1, 13):
        st.markdown(f"### {CZ_MONTHS[month]} {int(year)}")
        render_availability_grid(int(year), month, show_names=is_admin())  # ⬅️ přidáno
        st.markdown("---")

def occupied_name_map() -> dict:
    """
    Vrátí mapu {(room_type, date)->"Jméno (ID)"} pro každý obsazený den.
    Příjezd včetně, odjezd exkluzivně.
    """
    with get_conn() as con:
        rows = pd.read_sql_query("""
            SELECT rr.room_type, rr.arrival, rr.departure, r.id AS res_id, r.guest_name
            FROM reservation_rooms rr
            JOIN reservations r ON r.id = rr.id
            WHERE rr.room_type IS NOT NULL AND rr.room_type <> ''
        """, con)

    m = {}
    if rows.empty:
        return m

    for _, r in rows.iterrows():
        rt = str(r["room_type"])
        a = _parse_cz_date(str(r["arrival"]))
        d = _parse_cz_date(str(r["departure"]))
        if not rt or not a or not d or a >= d:
            continue
        label = f"{r['guest_name']} ({r['res_id']})" if r.get("guest_name") else str(r["res_id"])
        curr = a
        while curr < d:
            m[(rt, curr)] = label
            curr += timedelta(days=1)
    return m


def calendar_grid_ui():
    st.header("Kalendář obsazenosti")

    # inicializace stavu
    today = date.today()
    if "cal_year" not in st.session_state:
        st.session_state["cal_year"] = today.year
    if "cal_month" not in st.session_state:
        st.session_state["cal_month"] = today.month

    y = int(st.session_state["cal_year"])
    m = int(st.session_state["cal_month"])

    # horní ovládání
    cprev, ctitle, cnext = st.columns([1, 2, 1])

    if cprev.button("◀ Předchozí měsíc", key="prev_month"):
        _shift_month(-1)
        st.rerun()

    # 🔽 český název měsíce
    ctitle.markdown(f"### {CZ_MONTHS[m]} {y}")

    if cnext.button("Další měsíc ▶", key="next_month"):
        _shift_month(+1)
        st.rerun()

    st.markdown("---")

    render_availability_grid(y, m, show_names=is_admin())

def insert_request(payload: dict):
    with get_conn() as con:
        con.execute("""
            INSERT INTO requests(req_id, guest_name, contact, arrival, departure, nights, people, created_at, status, note)
            VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (
            payload["req_id"],
            payload["guest_name"],
            payload.get("contact"),
            payload.get("arrival"),
            payload.get("departure"),
            int(payload.get("nights", 0)),
            int(payload.get("people", 0)),
            payload.get("created_at"),
            payload.get("status", "nová"),
            payload.get("note", ""),
        ))
        con.commit()

def requests_admin_ui():
    import json

    if not is_admin():
        st.warning("Jen pro přihlášené (admin).")
        return

    st.header("Žádosti o rezervaci (admin)")

    # --- Filtr stavu ---
    stt = st.selectbox("Stav", ["vše", "nová", "schváleno", "zamítnuto", "vyřízeno"], index=0)

    # --- Načtení žádostí ---
    df = fetch_requests(stt)
    if df.empty:
        st.info("Žádné žádosti.")
        return

    # --- Přehledová tabulka ---
    base_cols = ["req_id","guest_name","contact","arrival","departure","nights","people","status","created_at"]
    show_cols = [c for c in base_cols if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    # --- Detail vybrané žádosti ---
    st.markdown("---")
    st.subheader("Detail žádosti")

    options = df["req_id"].tolist()
    req_id = st.selectbox("Vyber ID žádosti", options)

    sel = df[df["req_id"] == req_id].iloc[0]

    # Základní údaje v read-only polích
    c1, c2 = st.columns(2)
    c1.text_input("ID", value=str(sel["req_id"]), disabled=True)
    c2.text_input("Jméno", value=str(sel.get("guest_name") or ""), disabled=True)
    c3, c4, c5 = st.columns(3)
    c3.text_input("Příjezd", value=str(sel.get("arrival") or ""), disabled=True)
    c4.text_input("Odjezd", value=str(sel.get("departure") or ""), disabled=True)
    c5.number_input("Počet nocí", value=int(sel.get("nights") or 0), disabled=True)
    c6, c7 = st.columns(2)
    c6.number_input("Počet osob", value=int(sel.get("people") or 0), disabled=True)
    c7.text_input("Kontakt", value=str(sel.get("contact") or ""), disabled=True)
    st.text_area("Poznámka", value=str(sel.get("note") or ""), disabled=True)

    st.write(f"**Stav:** {str(sel.get('status') or '')} &nbsp;&nbsp; • &nbsp;&nbsp; **Vytvořeno:** {str(sel.get('created_at') or '')}")

    # --- Pokoje ze žádosti (rooms_json) ---
    rooms = []
    per_room_flag = False
    try:
        per_room_flag = bool(int(sel.get("per_room", 0))) if "per_room" in sel.index else False
    except Exception:
        per_room_flag = False

    rooms_json_val = None
    if "rooms_json" in sel.index:
        rooms_json_val = sel["rooms_json"]

    if rooms_json_val and str(rooms_json_val).strip():
        try:
            rooms = json.loads(rooms_json_val)
        except Exception as e:
            st.error(f"Nešlo načíst rooms_json: {e}")
            rooms = []

    if rooms:
        st.markdown("**Pokoje ze žádosti**")
        # Uspořádání sloupců pro přehlednost, pokud existují
        order = ["room_type","employees","guests","arrival","departure","nights"]
        df_rooms = pd.DataFrame(rooms)
        ordered = [c for c in order if c in df_rooms.columns] + [c for c in df_rooms.columns if c not in order]
        st.dataframe(df_rooms[ordered], use_container_width=True, hide_index=True)
    else:
        st.info("Žádost neobsahuje detail pokojů (rooms_json) nebo je prázdný.")

    # --- Akce ---
    ca, cb, cc, cd, ce = st.columns(5)

    if ca.button("Schválit"):
        update_request_status(req_id, "schváleno")
        st.success("Žádost schválena.")
        st.rerun()

    if cb.button("Zamítnout"):
        update_request_status(req_id, "zamítnuto")
        st.info("Žádost zamítnuta.")
        st.rerun()

    if cc.button("Označit jako vyřízeno"):
        update_request_status(req_id, "vyřízeno")
        st.success("Žádost označena jako vyřízená.")
        st.rerun()

    # Předvyplnění do admin formuláře (TEN SAMÝ obsah co zadal uživatel)
    if cd.button("Předvyplnit do 'Přidat/Upravit'"):
        pending = {
            "req_id": str(sel["req_id"]),
            "guest_name": str(sel.get("guest_name") or ""),
            "contact": str(sel.get("contact") or ""),
            "global_arrival": str(sel.get("arrival") or "") if not per_room_flag else "",
            "global_departure": str(sel.get("departure") or "") if not per_room_flag else "",
            "global_nights": int(sel.get("nights") or 0) if not per_room_flag else 0,
            "per_room": bool(per_room_flag),
            "rooms": rooms,                      # <<< KLÍČOVÉ: posíláme celé pokoje
            "note": str(sel.get("note") or ""),
        }
        st.session_state["pending_order"] = pending
        st.session_state["nav"] = "Přidat/Upravit"   # rovnou přepni na stránku s formulářem
        st.rerun()

    # Přímý převod žádosti na rezervaci (1 klik)
    if ce.button("Vytvořit rezervaci z žádosti", type="primary"):
        try:
            booking_id = create_reservation_from_request(req_id)
            st.success(f"Rezervace vytvořena. ID: {booking_id}")
        except Exception as e:
            st.error(f"Převod se nepodařil: {e}")

import pandas as pd
import numpy as np
import calendar as _cal

def style_month_grid(df, year: int, month: int):
    cal = _cal.Calendar(firstweekday=0)  # 0=pondělí vlevo; dej 6 pokud chceš neděli vlevo
    # poskládáme datumy do stejného tvaru jako df (6×7)
    dates = np.array(list(cal.itermonthdates(year, month))).reshape(df.shape)

    # víkend jen pro aktuální měsíc (dny z okolních měsíců necháme bílé)
    weekend_mask = np.vectorize(lambda d: (d.month == month) and (d.weekday() >= 5))(dates)

    styles = pd.DataFrame(
        np.where(weekend_mask, 'background-color:#f3f4f6', ''),
        index=df.index, columns=df.columns
    )
    # vrátíme Styler (bez typové anotace, aby se nic nevyhodnocovalo)
    return df.style.apply(lambda _: styles, axis=None)


def fetch_requests(status: Optional[str] = None) -> pd.DataFrame:
    with get_conn() as con:
        if status and status != "vše":
            return pd.read_sql_query("""
                SELECT * FROM requests WHERE status = ? ORDER BY created_at DESC
            """, con, params=(status,))
        else:
            return pd.read_sql_query("""
                SELECT * FROM requests ORDER BY created_at DESC
            """, con)

def update_request_status(req_id: str, new_status: str):
    with get_conn() as con:
        con.execute("UPDATE requests SET status = ? WHERE req_id = ?", (new_status, req_id))
        con.commit()


from zoneinfo import ZoneInfo
from datetime import datetime

def new_request_id(prefix: str = "REQ") -> str:
    now = datetime.now(ZoneInfo("Europe/Prague"))
    ts = now.strftime("%Y%m%d-%H%M%S")
    suf = secrets.token_hex(2).upper()
    return f"{prefix}-{ts}-{suf}"


def delete_by_id_ui():
    if not is_admin():
        st.warning("Tato stránka je jen pro přihlášené (admin).")
        return

    st.header("Smazat rezervaci podle ID")

    # načteme ID + jméno pro přehledný výběr
    with get_conn() as con:
        rows = con.execute("SELECT id, guest_name FROM reservations ORDER BY id DESC").fetchall()

    if not rows:
        st.info("Zatím nejsou žádné rezervace.")
        return

    labels = [f"{r[0]} — {r[1]}" for r in rows]
    label_to_id = {labels[i]: rows[i][0] for i in range(len(labels))}

    # výběr + tlačítko
    c1, c2 = st.columns([2,1])
    chosen_label = c1.selectbox("Vyber rezervaci", labels, key="del_select_label")
    show_btn = c2.button("Načíst detail")

    # stav náhledu: držíme booking_id v session_state, aby náhled nezmizel při rerunu
    if show_btn and chosen_label:
        st.session_state["del_preview_id"] = label_to_id[chosen_label]
        st.rerun()

    booking_id = st.session_state.get("del_preview_id")

    if not booking_id:
        st.info("Vyber rezervaci a klikni na „Načíst detail“.")
        return

    # --- read-only náhled vybrané rezervace ---
    hdr, rooms = fetch_detail(booking_id)
    if not hdr:
        st.error("ID nenalezeno.")
        return

    _id, guest_name, garr, gdep, gnights, per_room = hdr

    st.subheader("Detail (jen pro čtení)")
    cA, cB = st.columns(2)
    cA.text_input("ID", value=_id, disabled=True)
    cB.text_input("Jméno a příjmení", value=str(guest_name or ""), disabled=True)

    if per_room == 1:
        st.text_input("Režim datumů", value="Per-room", disabled=True)
    else:
        cC, cD, cE = st.columns(3)
        cC.text_input("Příjezd", value=str(garr or ""), disabled=True)
        cD.text_input("Odjezd", value=str(gdep or ""), disabled=True)
        cE.text_input("Nocí", value=str(gnights or 0), disabled=True)
        st.text_input("Režim datumů", value="Globální", disabled=True)

    data = []
    total = 0.0
    for r in rooms:
        room_idx, room_type, employees, guests, arr, dep, nights, price = r
        total += float(price or 0.0)
        a = arr or garr or ""
        d = dep or gdep or ""
        n = int(nights or gnights or 0)
        data.append({
            "Pokoj #": int(room_idx),
            "Typ": room_type or "",
            "Zam.": int(employees or 0),
            "Hosté": int(guests or 0),
            "Příjezd": a,
            "Odjezd": d,
            "Nocí": n,
            "Cena (Kč)": int(price or 0),
        })

    st.markdown("**Pokoje**")
    df_display = pd.DataFrame(data)

    # vynutit celočíselný sloupec ceny (žádné .0)
    if "Cena (Kč)" in df_display.columns:
        df_display["Cena (Kč)"] = df_display["Cena (Kč)"].astype("Int64")

    # === zajisti, že CenaCelkem je celé číslo ===
    if "CenaCelkem" in df_display.columns:
        df_display["CenaCelkem"] = (
            pd.to_numeric(df_display["CenaCelkem"], errors="coerce")  # čísla z výpočtu/řetězců
            .round(0)  # zaokrouhli
            .astype("Int64")  # Pandas integer s podporou <NA>
        )

    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Cena (Kč)": st.column_config.NumberColumn(format="%d")  # žádná desetinná místa
        }
    )
    st.markdown(f"**Celkem:** {int(total)} Kč")

    # --- potvrzení a smazání (stav se drží, náhled nezmizí) ---
    st.markdown("---")
    st.error("Pozor: smazání je trvalé (reservations, reservation_rooms, participants).")

    col1, col2 = st.columns([2, 1])
    confirm_checked = col1.checkbox("Rozumím a chci rezervaci trvale smazat.", key="del_confirm_checked")
    typed = col1.text_input("Pro potvrzení zadej přesně ID rezervace:", value="", key="del_confirm_typed")

    delete_disabled = not (confirm_checked and typed == _id)
    if col2.button("Smazat rezervaci", type="primary", disabled=delete_disabled, key="del_execute"):
        try:
            delete_participants_by_id(_id)
            delete_by_id(_id)
            st.success(f"Rezervace {_id} byla smazána.")
            # vyčistíme stav náhledu, aby zmizel detail
            st.session_state.pop("del_preview_id", None)
            st.session_state.pop("del_confirm_checked", None)
            st.session_state.pop("del_confirm_typed", None)
            st.rerun()
        except Exception as e:
            st.error(f"Smazání selhalo: {e}")


def main():
    st.set_page_config(page_title="Rezervace", layout="wide")
    # >>> ZAJISTÍ FONTY A MAPOVÁNÍ (bold/italic) JEŠTĚ PŘED GENEROVÁNÍM PDF <<<
    try:
        ensure_czech_fonts()
    except Exception as e:
        st.error(f"Fonty DejaVuSans nejsou připravené: {e}")
        # nepřestřelíme celé UI, ale PDF do té doby nepůjde



    # 1) Výběr lokality než se vůbec ukáže appka
    if "site" not in st.session_state:
        site_login_ui()
        return



    # 2) Přihlášení (jen když nejsi přihlášen v žádné roli)
    if current_role() == "public":
        login_box()

    sidebar_site_badge()
    init_db()

    st.sidebar.title("Menu")

    role = current_role()
    if role == "admin":
        pages = [
            "Přehled",
            "Přidat",
            "Upravit podle ID",
            "Kalendář - měsíc",
            "Kalendář - celý rok",
            "Žádosti",
            "Účastníci",
            "Poukaz (PDF)",
            "Smazat podle ID",
        ]
    elif role == "dohled":
        pages = [
            "Přehled",
            "Kalendář - celý rok",
            "Kalendář - měsíc",
            "Účastníci",
            "Poukaz (PDF)",
        ]
    else:  # public
        pages = [
            "Kalendář - měsíc",
            "Kalendář - celý rok",
            "Žádost o rezervaci",

        ]

    # reset volby navigace, pokud stará volba už není v novém seznamu
    if st.session_state.get("nav") not in pages:
        st.session_state["nav"] = pages[0]
    page = st.sidebar.radio("Navigace", pages, key="nav")

    # 3) Router s guardy podle role
    if page == "Přehled":
        if role in ("admin", "dohled"):
            overview_ui()
        else:
            st.warning("Jen pro přihlášené.")
    elif page == "Přidat":
        if role == "admin":
            booking_form()
        else:
            st.warning("Jen pro admina.")
    elif page == "Upravit podle ID":
        if role == "admin":
            edit_by_id_ui()
            st.markdown("---")
            booking_form(st.session_state.get("edit_id", ""))
        else:
            st.warning("Jen pro admina.")
    elif page == "Kalendář - měsíc":
        calendar_grid_ui()
    elif page == "Kalendář - celý rok":
        calendar_year_ui()
    elif page == "Žádosti":
        if role == "admin":
            requests_admin_ui()
        else:
            st.warning("Jen pro admina.")
    elif page == "Žádost o rezervaci":
            booking_form_unified(mode="public")
    elif page == "Přidat":
        if role == "admin":
            booking_form_unified(mode="admin")
    elif page == "Účastníci":
        if role in ("admin", "dohled"):
            participants_ui()
        else:
            st.warning("Jen pro přihlášené.")
    elif page == "Poukaz (PDF)":
        if role in ("admin", "dohled"):
            voucher_ui()
        else:
            st.warning("Jen pro přihlášené.")
    elif page == "Smazat podle ID":
        if role == "admin":
            delete_by_id_ui()
        else:
            st.warning("Jen pro admina.")


if __name__ == "__main__":
    main()