import sqlite3
from datetime import date
from typing import List, Dict, Optional
import secrets  # pro krátký náhodný suffix


import pandas as pd
import streamlit as st


MAX_ROOMS = 6

# --- MULTI-SITE (Hejnice / Dobrejov) ---
SITES = {
    "Hejnice": {
        "db": "reservations_hejnice.db",
        "config": "config_Hejnice.csv",
    },
    "Dobřejov": {
        "db": "reservations_dobrejov.db",
        "config": "config_Dobřejov.csv",
    },
}

CZ_MONTHS = [
    "",  # index 0 prázdný (aby 1=leden)
    "Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
    "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec"
]

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

def is_admin() -> bool:
    return bool(st.session_state.get("is_admin", False))

def logout_admin():
    st.session_state["is_admin"] = False

def login_box():
    st.sidebar.markdown("### Přihlášení")
    pwd = st.sidebar.text_input("Heslo", type="password")
    if st.sidebar.button("Přihlásit"):
        # 1) přes st.secrets
        secret = st.secrets.get("ADMIN_PASSWORD", "")
        # 2) případně alternativně z env proměnné:
        # import os; secret = os.getenv("ADMIN_PASSWORD", "")
        if pwd and secret and pwd == secret:
            st.session_state["is_admin"] = True
            st.sidebar.success("Přihlášení OK.")
            st.rerun()
        else:
            st.sidebar.error("Neplatné heslo.")

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


def site_login_ui():
    st.title("Rezervace – výběr lokality")
    st.write("Vyber prosím objekt, se kterým chceš pracovat:")
    site = st.radio("Lokalita", list(SITES.keys()))
    if st.button("Pokračovat"):
        st.session_state.clear()
        st.session_state["site"] = site
        st.rerun()


# ---------- DB ----------


def get_conn():
    db_path, _ = current_paths()
    if not db_path:
        raise RuntimeError("Lokalita není zvolena.")
    return sqlite3.connect(db_path, check_same_thread=False)

@st.cache_data(show_spinner=False)
def load_config_for_path(config_path: str) -> pd.DataFrame:
    df = pd.read_csv(config_path, encoding="utf-8")
    df.columns = [c.strip().upper() for c in df.columns]
    # povinné sloupce
    for req in ("POKOJ", "CENA_Z", "CENA_N"):
        if req not in df.columns:
            raise ValueError(f"V configu chybí sloupec: {req}")
    return df

def get_cfg() -> pd.DataFrame:
    _, cfg_path = current_paths()
    if not cfg_path:
        raise RuntimeError("Lokalita není zvolena.")
    return load_config_for_path(cfg_path)



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

def create_voucher_pdf_bytes_participants(booking_id: str) -> bytes:
    # Unicode fonty pro češtinu (dej do projektu DejaVuSans.ttf / DejaVuSans-Bold.ttf)
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "DejaVuSans-Bold.ttf"))
        base_font = "DejaVuSans"
        bold_font = "DejaVuSans-Bold"
    except Exception:
        base_font = "Helvetica"
        bold_font = "Helvetica-Bold"

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
    styles["Normal"].fontName = base_font
    styles["Title"].fontName = bold_font
    styles["Heading3"].fontName = bold_font
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontName=base_font, fontSize=9))

    story = []
    story.append(Paragraph("POUKAZ / ÚČASTNÍCI", styles["Title"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"ID rezervace: <b>{_id}</b>", styles["Normal"]))
    story.append(Paragraph(f"Jméno: <b>{guest_name}</b>", styles["Normal"]))
    if per_room == 1:
        story.append(Paragraph("Režim datumů: <b>per-room</b>", styles["Normal"]))
    else:
        story.append(Paragraph("Režim datumů: <b>globální</b>", styles["Normal"]))
        story.append(Paragraph(f"Příjezd: <b>{garr or ''}</b> &nbsp;&nbsp; Odjezd: <b>{gdep or ''}</b> &nbsp;&nbsp; Nocí: <b>{gnights or 0}</b>", styles["Normal"]))
    story.append(Spacer(1, 8))

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
        ("ALIGN", (1,1), (1,-1), "LEFT"),
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
                   COALESCE(SUM(rr.price),0) AS CenaCelkem,
                   COUNT(rr.room_idx) AS PocetPokoju
            FROM reservations r
            LEFT JOIN reservation_rooms rr ON r.id = rr.id
            GROUP BY r.id, r.guest_name, r.global_arrival, r.global_departure, r.global_nights, r.per_room
            ORDER BY r.id DESC                -- ⬅️ nejnovější první
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
                em = c2.number_input(f"Zam {i}", min_value=0, step=1, key=f"em_{i}", label_visibility="collapsed")
                gu = c3.number_input(f"Hoste {i}", min_value=0, step=1, key=f"gu_{i}", label_visibility="collapsed")

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
                em = c2.number_input(f"Zam {i}", min_value=0, step=1, key=f"em_{i}", label_visibility="collapsed")
                gu = c3.number_input(f"Hoste {i}", min_value=0, step=1, key=f"gu_{i}", label_visibility="collapsed")

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
                rr.price                AS Cena
            FROM reservations r
            JOIN reservation_rooms rr ON r.id = rr.id
            ORDER BY r.id DESC, rr.room_idx  -- ⬅️ nejnovější rezervace nahoře, pokoje v rámci ID
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
from datetime import timedelta

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

def calendar_ui():
    st.header("Kalendář obsazenosti (podle typu pokoje)")
    cfg = get_cfg()
    room_types = cfg["POKOJ"].tolist()
    if not room_types:
        st.warning("V config_Hejnice.csv nejsou žádné typy pokojů.")
        return

    c1, c2, c3 = st.columns(3)
    rt = c1.selectbox("Typ pokoje", room_types)
    today = date.today()
    year = c2.number_input("Rok", min_value=2000, max_value=2100, value=today.year, step=1)
    month = c3.number_input("Měsíc", min_value=1, max_value=12, value=today.month, step=1)

    av = availability_for_month_bool(rt, int(year), int(month))
    render_calendar_matrix_bool(av, int(year), int(month))

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

from datetime import date
from typing import Optional

def booking_form(edit_id: Optional[str] = None):
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

    st.dataframe(df, use_container_width=True)

from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def create_voucher_pdf_bytes(booking_id: str) -> bytes:
    # >>> REGISTRACE UNICODE FONTŮ <<<
    try:
        pdfmetrics.registerFont(TTFont("DejaVuSans", "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", "DejaVuSans-Bold.ttf"))
    except Exception:
        # fallback: když fonty nejsou, PDF se vygeneruje, ale diakritika nebude
        pass

    hdr, rooms = fetch_detail(booking_id)
    if not hdr:
        raise ValueError("ID nenalezeno.")
    _id, guest_name, garr, gdep, gnights, per_room = hdr

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()

    # >>> POUŽÍT UNICODE STYLY <<<
    base_font = "DejaVuSans" if "DejaVuSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
    bold_font = "DejaVuSans-Bold" if "DejaVuSans-Bold" in pdfmetrics.getRegisteredFontNames() else "Helvetica-Bold"

    styles["Normal"].fontName = base_font
    styles["Title"].fontName = bold_font
    styles["Heading3"].fontName = bold_font

    # (volitelně vytvořím „Small“ styl)
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontName=base_font, fontSize=9))

    story = []
    story.append(Paragraph("POUKAZ / REZERVACE", styles["Title"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"ID rezervace: <b>{_id}</b>", styles["Normal"]))
    story.append(Paragraph(f"Jméno: <b>{guest_name}</b>", styles["Normal"]))
    if per_room == 1:
        story.append(Paragraph("Režim datumů: <b>per-room</b>", styles["Normal"]))
    else:
        story.append(Paragraph("Režim datumů: <b>globální</b>", styles["Normal"]))
        story.append(Paragraph(f"Příjezd: <b>{garr or ''}</b> &nbsp;&nbsp; Odjezd: <b>{gdep or ''}</b> &nbsp;&nbsp; Nocí: <b>{gnights or 0}</b>", styles["Normal"]))
    story.append(Spacer(1, 8))

    # Tabulka
    data = [["#", "Pokoj", "Zam.", "Hosté", "Příjezd", "Odjezd", "Nocí", "Cena (Kč)"]]
    total = 0.0
    for idx, r in enumerate(rooms, start=1):
        room_idx, room_type, employees, guests, arr, dep, nights, price = r
        total += float(price or 0.0)
        a, d, n = (arr or garr or ""), (dep or gdep or ""), (nights or gnights or 0)
        data.append([idx, room_type or "", int(employees or 0), int(guests or 0), a, d, int(n), int(price or 0)])

    tbl = Table(data, colWidths=[8*mm, 35*mm, 14*mm, 16*mm, 24*mm, 24*mm, 12*mm, 24*mm])
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), base_font),         # <<< používej Unicode font
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
        ("GRID", (0,0), (-1,-1), 0.3, colors.grey),
        ("ALIGN", (0,0), (-1,0), "CENTER"),
        ("ALIGN", (0,1), (0,-1), "CENTER"),
        ("ALIGN", (2,1), (3,-1), "CENTER"),
        ("ALIGN", (6,1), (7,-1), "RIGHT"),
        ("FONTNAME", (0,0), (-1,0), bold_font),          # hlavička tučně
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


def voucher_ui():
    st.header("Vygenerovat poukaz (PDF)")
    # načteme ID + jméno
    with get_conn() as con:
        rows = con.execute("SELECT id, guest_name FROM reservations ORDER BY id DESC").fetchall()
    if not rows:
        st.info("Zatím nejsou žádné rezervace.")
        return

    # připravíme mapu: label -> id
    options = [f"{r[0]} — {r[1]}" for r in rows]  # „ID — Jméno“
    label_to_id = {opt: rows[i][0] for i, opt in enumerate(options)}

    c1, c2 = st.columns([2,1])
    chosen_label = c1.selectbox("Vyber rezervaci", options)
    if c2.button("Vygenerovat poukaz"):
        booking_id = label_to_id[chosen_label]
        try:
            pdf_bytes = create_voucher_pdf_bytes(booking_id)
            st.success("Poukaz vygenerován.")
            st.download_button(
                label="Stáhnout poukaz PDF",
                data=pdf_bytes,
                file_name=f"poukaz_{booking_id}.pdf",
                mime="application/pdf",
            )
        except Exception as e:
            st.error(f"Nepodařilo se vygenerovat poukaz: {e}")


def sidebar_site_badge():
    site = st.session_state.get("site")
    if site:
        st.sidebar.success(f"Aktivní: **{site}**")
        if st.sidebar.button("Změnit lokalitu"):
            st.session_state.clear()
            st.rerun()  # dříve: st.experimental_rerun()
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
    st.header("Kalendář obsazenosti (grid)")

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

def request_form_public_ui():
    st.header("Žádost o rezervaci")

    with st.form("request_form"):
        c1, c2 = st.columns([2,1])
        guest_name = c1.text_input("Jméno a příjmení*")
        contact = c2.text_input("Kontakt (e-mail/telefon)*")

        c3, c4, c5 = st.columns([1,1,1])
        arr = c3.date_input("Příjezd*", value=date.today(), format="DD.MM.YYYY")
        dep = c4.date_input("Odjezd*", value=date.today(), format="DD.MM.YYYY")
        people = c5.number_input("Počet osob*", min_value=1, step=1, value=1)

        note = st.text_area("Poznámka (nepovinné)", placeholder="Např. preferovaný pokoj, dietní omezení apod.")

        submitted = st.form_submit_button("Odeslat žádost")

    if not submitted:
        st.info("Po odeslání vás budeme kontaktovat. Toto není závazná rezervace.")
        return

    # validace
    if not guest_name.strip() or not contact.strip():
        st.error("Vyplňte jméno i kontakt.")
        return
    nights = max(0, days_between(arr, dep))
    if nights <= 0:
        st.error("Odjezd musí být po příjezdu (minimálně 1 noc).")
        return

    payload = {
        "req_id": new_request_id(),
        "guest_name": guest_name.strip(),
        "contact": contact.strip(),
        "arrival": arr.strftime("%d.%m.%Y"),
        "departure": dep.strftime("%d.%m.%Y"),
        "nights": nights,
        "people": int(people),
        "created_at": datetime.now(ZoneInfo("Europe/Prague")).strftime("%Y-%m-%d %H:%M:%S"),
        "status": "nová",
        "note": note.strip(),
    }
    try:
        insert_request(payload)
        st.success(f"Žádost byla odeslána. ID žádosti: {payload['req_id']}. Ozveme se vám.")
    except Exception as e:
        st.error(f"Odeslání se nezdařilo: {e}")

def requests_admin_ui():
    if not is_admin():
        st.warning("Jen pro přihlášené (admin).")
        return

    st.header("Žádosti o rezervaci (admin)")

    # filtr
    stt = st.selectbox("Stav", ["vše", "nová", "schváleno", "zamítnuto", "vyřízeno"], index=0)
    df = fetch_requests(stt)
    if df.empty:
        st.info("Žádné žádosti.")
        return

    # zobrazení
    show_cols = ["req_id","guest_name","contact","arrival","departure","nights","people","status","created_at"]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    # výběr pro detail
    st.markdown("---")
    st.subheader("Detail žádosti")
    options = df["req_id"].tolist()
    req_id = st.selectbox("Vyber ID žádosti", options)

    sel = df[df["req_id"] == req_id].iloc[0]
    c1, c2 = st.columns(2)
    c1.text_input("ID", value=sel["req_id"], disabled=True)
    c2.text_input("Jméno", value=str(sel["guest_name"]), disabled=True)
    c3, c4, c5 = st.columns(3)
    c3.text_input("Příjezd", value=str(sel["arrival"]), disabled=True)
    c4.text_input("Odjezd", value=str(sel["departure"]), disabled=True)
    c5.number_input("Počet nocí", value=int(sel["nights"] or 0), disabled=True)
    c6, c7 = st.columns(2)
    c6.number_input("Počet osob", value=int(sel["people"] or 0), disabled=True)
    c7.text_input("Kontakt", value=str(sel["contact"]), disabled=True)
    st.text_area("Poznámka", value=str(sel.get("note") or ""), disabled=True)

    st.write(f"**Stav:** {sel['status']} &nbsp;&nbsp; • &nbsp;&nbsp; **Vytvořeno:** {sel['created_at']}")

    # akce
    ca, cb, cc, cd = st.columns(4)
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

    # předvyplnění do formuláře rezervace
    if cd.button("Předvyplnit do 'Přidat/Upravit'"):
        # zkusíme uložit prefily pro booking_form
        st.session_state["guest_name_prefill"] = str(sel["guest_name"])
        # naparsovat data na date
        def _try_parse(dmy: str) -> Optional[date]:
            try:
                d, m, y = [int(x) for x in str(dmy).split(".")]
                return date(y, m, d)
            except Exception:
                return None
        ga = _try_parse(sel["arrival"])
        gd = _try_parse(sel["departure"])
        if ga: st.session_state["global_arrival_tmp"] = ga
        if gd: st.session_state["global_departure_tmp"] = gd
        st.info("Otevři teď stránku 'Přidat/Upravit' – údaje jsou předvyplněné.")

def requests_admin_ui():
    if not is_admin():
        st.warning("Jen pro přihlášené (admin).")
        return

    st.header("Žádosti o rezervaci (admin)")

    # filtr
    stt = st.selectbox("Stav", ["vše", "nová", "schváleno", "zamítnuto", "vyřízeno"], index=0)
    df = fetch_requests(stt)
    if df.empty:
        st.info("Žádné žádosti.")
        return

    # zobrazení
    show_cols = ["req_id","guest_name","contact","arrival","departure","nights","people","status","created_at"]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

    # výběr pro detail
    st.markdown("---")
    st.subheader("Detail žádosti")
    options = df["req_id"].tolist()
    req_id = st.selectbox("Vyber ID žádosti", options)

    sel = df[df["req_id"] == req_id].iloc[0]
    c1, c2 = st.columns(2)
    c1.text_input("ID", value=sel["req_id"], disabled=True)
    c2.text_input("Jméno", value=str(sel["guest_name"]), disabled=True)
    c3, c4, c5 = st.columns(3)
    c3.text_input("Příjezd", value=str(sel["arrival"]), disabled=True)
    c4.text_input("Odjezd", value=str(sel["departure"]), disabled=True)
    c5.number_input("Počet nocí", value=int(sel["nights"] or 0), disabled=True)
    c6, c7 = st.columns(2)
    c6.number_input("Počet osob", value=int(sel["people"] or 0), disabled=True)
    c7.text_input("Kontakt", value=str(sel["contact"]), disabled=True)
    st.text_area("Poznámka", value=str(sel.get("note") or ""), disabled=True)

    st.write(f"**Stav:** {sel['status']} &nbsp;&nbsp; • &nbsp;&nbsp; **Vytvořeno:** {sel['created_at']}")

    # akce
    ca, cb, cc, cd = st.columns(4)
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

    # předvyplnění do formuláře rezervace
    if cd.button("Předvyplnit do 'Přidat/Upravit'"):
        # zkusíme uložit prefily pro booking_form
        st.session_state["guest_name_prefill"] = str(sel["guest_name"])
        # naparsovat data na date
        def _try_parse(dmy: str) -> Optional[date]:
            try:
                d, m, y = [int(x) for x in str(dmy).split(".")]
                return date(y, m, d)
            except Exception:
                return None
        ga = _try_parse(sel["arrival"])
        gd = _try_parse(sel["departure"])
        if ga: st.session_state["global_arrival_tmp"] = ga
        if gd: st.session_state["global_departure_tmp"] = gd
        st.info("Otevři teď stránku 'Přidat/Upravit' – údaje jsou předvyplněné.")


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
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
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

    if "site" not in st.session_state:
        site_login_ui()
        return

    sidebar_site_badge()
    init_db()

    # AUTH box (jak už máš)
    if is_admin():
        st.sidebar.success("Režim: Admin")
        if st.sidebar.button("Odhlásit"):
            logout_admin()
            st.rerun()
    else:
        login_box()

    st.sidebar.title("Menu")

    if is_admin():
        page = st.sidebar.radio(
            "Navigace",
            [
                "Přehled",
                "Přidat/Upravit",
                "Upravit podle ID (rychlé)",
                "Smazat podle ID",

                "Kalendář (grid)",
                "Kalendář (rok)",

                "Účastníci",
                "Poukaz (PDF)",
                "Žádosti",
            ]
        )
    else:
        page = st.sidebar.radio(
            "Navigace",
            [
                "Kalendář (rok)",

                "Kalendář (grid)",

                "Žádost o rezervaci",  # ⬅️ veřejná stránka
            ]
        )

    st.sidebar.info("Ceník se načítá z configu vybrané lokality")

    # router
    if page == "Přehled":
        overview_ui()
    elif page == "Přidat/Upravit":
        booking_form()
    elif page == "Upravit podle ID (rychlé)":
        edit_by_id_ui()
        st.markdown("---")
        booking_form(st.session_state.get("edit_id", ""))
    elif page == "Kalendář (grid)":
        calendar_grid_ui()
    elif page == "Kalendář (rok)":
        calendar_year_ui()
    elif page == "Žádosti":
        requests_admin_ui()
    elif page == "Žádost o rezervaci":
        request_form_public_ui()
    elif page == "Účastníci":
        participants_ui()
    elif page == "Poukaz (PDF)":
        voucher_ui()
    else:
        delete_by_id_ui()

if __name__ == "__main__":
    main()
