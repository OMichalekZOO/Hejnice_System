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
    with get_conn() as con:
        cur = con.cursor()

        # pokud nepřepisujeme a ID už existuje → chyba
        if not overwrite:
            exists = cur.execute("SELECT 1 FROM reservations WHERE id = ?", (header["id"],)).fetchone()
            if exists:
                raise ValueError(f"Rezervace s ID '{header['id']}' už existuje.")

        # když přepisujeme, smažeme staré řádky s tím ID
        if overwrite:
            cur.execute("DELETE FROM reservations WHERE id = ?", (header["id"],))
            cur.execute("DELETE FROM reservation_rooms WHERE id = ?", (header["id"],))

        # vložit hlavičku
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

        # vložit pokoje
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
            ORDER BY r.id
        """, con)
    return df

# ---------- UI ----------
def rooms_form(per_room: bool, cfg: pd.DataFrame, global_arrival: Optional[date], global_departure: Optional[date]):
    st.subheader("Pokoje")
    room_types = [""] + cfg["POKOJ"].tolist()

    rooms_payload = []
    total_price = 0.0
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

    for i in range(1, MAX_ROOMS+1):
        with st.container():
            if per_room:
                c1, c2, c3, c4, c5, c6, c7 = st.columns([2,1,1,2,2,1,1])
                rt = c1.selectbox(f"Typ {i}", room_types, key=f"rt_{i}", label_visibility="collapsed")
                em = c2.number_input(f"Zam {i}", min_value=0, step=1, key=f"em_{i}", label_visibility="collapsed")
                gu = c3.number_input(f"Hoste {i}", min_value=0, step=1, key=f"gu_{i}", label_visibility="collapsed")
                arr = c4.date_input(f"Arr {i}", value=global_arrival or date.today(), key=f"arr_{i}", format="DD.MM.YYYY", label_visibility="collapsed")
                dep = c5.date_input(f"Dep {i}", value=global_departure or date.today(), key=f"dep_{i}", format="DD.MM.YYYY", label_visibility="collapsed")
                nights = max(0, days_between(arr, dep))
                c6.write(nights)
                pr = price_for(rt, em, gu, nights, cfg)
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

    st.markdown(f"**Cena celkem:** {int(total_price)}")
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
            ORDER BY r.id, rr.room_idx
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

def booking_form(edit_id: Optional[str] = None):
    cfg = get_cfg()

    st.header("Rezervace")

    # === FORM start ===
    with st.form("booking_form"):
        # --- Základní údaje ---
        c1, c2 = st.columns(2)
        guest_name = c1.text_input(
            "Jméno a příjmení",
            value=st.session_state.get("guest_name_prefill", "")
        )

        # --- ID rezervace (auto) ---
        if edit_id:
            booking_id = edit_id
            c2.text_input("ID rezervace", value=booking_id, disabled=True, help="ID nelze měnit v režimu úprav.")
            regen_clicked = False
        else:
            if "auto_booking_id" not in st.session_state:
                st.session_state["auto_booking_id"] = new_booking_id()
            c2.text_input(
                "ID rezervace",
                value=st.session_state["auto_booking_id"],
                disabled=True,
                help="ID se generuje automaticky."
            )

        # --- Datumový režim ---
        c3, c4, c5 = st.columns([1, 1, 1])
        per_room = c3.checkbox("Vlastní datumy pro každý pokoj (per-room)", value=False)

        if per_room:
            st.info("Per-room: datumy vybírejte u každého pokoje. Globální datumy jsou ignorovány.")
            global_arrival = None
            global_departure = None
            global_nights = 0
        else:
            global_arrival = c4.date_input("Příjezd", value=date.today(), format="DD.MM.YYYY")
            global_departure = c5.date_input("Odjezd", value=date.today(), format="DD.MM.YYYY")
            global_nights = max(0, days_between(global_arrival, global_departure))
            st.write(f"Nocí: **{global_nights}**")

        # --- Pokoje + ceny (živý přepočet) ---
        rooms_payload = rooms_form(per_room, cfg, global_arrival, global_departure)

        st.markdown("---")

        # --- Ovládací prvky formu ---
        colA, colB = st.columns([1, 2])

        # a) vygenerovat nové ID (jen v režimu přidání)
        if not edit_id:
            regen_clicked = colA.form_submit_button("Vygenerovat nové ID")
        else:
            regen_clicked = False

        # b) uložit
        save_clicked = colB.form_submit_button("Vložit rezervaci")

    # === FORM end ===

    # Handler pro vygenerování nového ID
    if regen_clicked and not edit_id:
        st.session_state["auto_booking_id"] = new_booking_id()
        st.rerun()

    # Handler pro uložení (mimo with form:)
    if save_clicked:
        overwrite = bool(edit_id)  # v edit režimu přepisujeme, jinak vkládáme
        if not guest_name.strip():
            st.error("Vyplň jméno.")
            return
        if len(rooms_payload) == 0:
            st.error("Vyber aspoň jeden pokoj (vyplň typ).")
            return

        booking_id = edit_id or st.session_state["auto_booking_id"]
        header = {
            "id": booking_id.strip(),
            "guest_name": guest_name.strip(),
            "global_arrival": global_arrival.strftime("%d.%m.%Y") if global_arrival else None,
            "global_departure": global_departure.strftime("%d.%m.%Y") if global_departure else None,
            "global_nights": global_nights,
            "per_room": per_room
        }
        try:
            insert_or_replace_booking(header, rooms_payload, overwrite=overwrite)
            st.success(f"Rezervace uložena. ID: {booking_id}")
            if not edit_id:
                # připrav nové ID pro další záznam
                st.session_state["auto_booking_id"] = new_booking_id()
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

def overview_ui():
    st.header("Přehled rezervací")

    mode = st.radio("Zobrazení", ["Souhrn (1 řádek na rezervaci)", "Po pokojích (1 řádek na pokoj)"], index=0)

    if mode.startswith("Souhrn"):
        df = fetch_overview()
    else:
        df = fetch_overview_rooms()

    st.dataframe(df, use_container_width=True)

    if not df.empty:
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Stáhnout CSV", csv, "rezervace_prehled.csv", "text/csv")


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

def render_availability_grid(year: int, month: int):
    df = availability_matrix(year, month)
    if df.empty:
        st.warning("Žádné pokoje v configu nebo prázdná data.")
        return

    # převedeme na HTML
    html = "<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
    # hlavička
    html += "<tr><th style='border:1px solid #ccc;padding:2px;text-align:center;'>Pokoj</th>"
    for col in df.columns:
        html += f"<th style='border:1px solid #ccc;padding:2px;text-align:center;'>{col}</th>"
    html += "</tr>"

    # řádky
    for room, row in df.iterrows():
        html += f"<tr><td style='border:1px solid #ccc;padding:2px;text-align:left;font-weight:bold;'>{room}</td>"
        for val in row:
            color = "#2ecc71" if val else "#e74c3c"  # zelená/červená
            html += f"<td style='border:1px solid #ccc;padding:6px;background:{color};'></td>"
        html += "</tr>"

    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)

def calendar_grid_ui():
    st.header("Kalendář obsazenosti (grid)")

    # výchozí měsíc/rok do session_state
    today = date.today()
    if "cal_year" not in st.session_state:
        st.session_state["cal_year"] = today.year
    if "cal_month" not in st.session_state:
        st.session_state["cal_month"] = today.month

    # horní ovládání
    cprev, ctitle, cnext = st.columns([1, 2, 1])
    if cprev.button("◀ Předchozí měsíc"):
        y, m = st.session_state["cal_year"], st.session_state["cal_month"]
        if m == 1:
            st.session_state["cal_month"] = 12
            st.session_state["cal_year"] = y - 1
        else:
            st.session_state["cal_month"] = m - 1

    ctitle.markdown(
        f"### {__import__('calendar').month_name[st.session_state['cal_month']]} {st.session_state['cal_year']}"
    )

    if cnext.button("Další měsíc ▶"):
        y, m = st.session_state["cal_year"], st.session_state["cal_month"]
        if m == 12:
            st.session_state["cal_month"] = 1
            st.session_state["cal_year"] = y + 1
        else:
            st.session_state["cal_month"] = m + 1

    st.markdown("---")
    render_availability_grid(int(st.session_state["cal_year"]), int(st.session_state["cal_month"]))

def main():
    st.set_page_config(page_title="Rezervace", layout="wide")

    # 1) Pokud není vybraná lokalita, ukaž login a skonči
    if "site" not in st.session_state:
        site_login_ui()
        return

    # 2) Sidebar badge a init DB pro tuhle lokalitu
    sidebar_site_badge()
    init_db()

    # 3) Menu appky
    st.sidebar.title("Menu")
    page = st.sidebar.radio(
        "Navigace",
        [
            "Přehled",
            "Přidat/Upravit",
            "Upravit podle ID (rychlé)",
            "Kalendář (grid)",
            "Účastníci",
            "Poukaz (PDF)",
        ]
    )
    st.sidebar.info("Ceník se načítá z configu vybrané lokality")

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
    elif page == "Účastníci":
        participants_ui()
    else:
        voucher_ui()

if __name__ == "__main__":
    main()
