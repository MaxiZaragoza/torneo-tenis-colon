import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g, session

app = Flask(__name__)
app.secret_key = "clave_secreta_admin"
DATABASE = "torneo_tenis.db"
ADMIN_PASSWORD = "Maxi2026"


def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON;")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS zonas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                categoria TEXT NOT NULL DEFAULT '3era'
            )
        """)

        cursor.execute("PRAGMA table_info(zonas)")
        cols = [col[1] for col in cursor.fetchall()]
        if "categoria" not in cols:
            cursor.execute("ALTER TABLE zonas ADD COLUMN categoria TEXT NOT NULL DEFAULT '3era'")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jugadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                zona_id INTEGER NOT NULL,
                FOREIGN KEY (zona_id) REFERENCES zonas (id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS partidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zona_id INTEGER NOT NULL,
                jugador1_id INTEGER NOT NULL,
                jugador2_id INTEGER NOT NULL,
                resultado_texto TEXT NOT NULL,
                sets_ganados1 INTEGER NOT NULL,
                sets_ganados2 INTEGER NOT NULL,
                games_totales1 INTEGER NOT NULL,
                games_totales2 INTEGER NOT NULL,
                FOREIGN KEY (zona_id) REFERENCES zonas (id) ON DELETE CASCADE,
                FOREIGN KEY (jugador1_id) REFERENCES jugadores (id) ON DELETE CASCADE,
                FOREIGN KEY (jugador2_id) REFERENCES jugadores (id) ON DELETE CASCADE,
                UNIQUE(zona_id, jugador1_id, jugador2_id)
            )
        """)

        # Nueva Tabla para los Cuadros de Eliminación Directa
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cuadros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria TEXT NOT NULL,
                instancia TEXT NOT NULL,
                partido_num INTEGER NOT NULL,
                jugador1_nombre TEXT DEFAULT '',
                jugador2_nombre TEXT DEFAULT '',
                resultado TEXT DEFAULT '',
                UNIQUE(categoria, instancia, partido_num)
            )
        """)

        # Inicializar los casilleros del cuadro si no existen
        instancias_config = [
            ("cuartos", 4),
            ("semi", 2),
            ("final", 1)
        ]
        for cat in ["3era", "4ta"]:
            for inst, cant in instancias_config:
                for num in range(1, cant + 1):
                    cursor.execute("""
                        INSERT OR IGNORE INTO cuadros (categoria, instancia, partido_num)
                        VALUES (?, ?, ?)
                    """, (cat, inst, num))

        db.commit()


init_db()


def parse_sets_para_vista(res_txt):
    if not res_txt: return []
    tokens = [s.strip() for s in res_txt.split(",") if s.strip()]
    sets_data = []
    for t in tokens:
        if "-" in t:
            s1, s2 = t.split("-")
            try:
                g1, g2 = int(s1), int(s2)
                sets_data.append({"texto": f"{g1}-{g2}", "ganado": g1 > g2})
            except ValueError:
                sets_data.append({"texto": t, "ganado": False})
    return sets_data


def obtener_datos_torneo():
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM zonas ORDER BY categoria, nombre")
    zonas_raw = cursor.fetchall()

    categorias_data = {"3era": [], "4ta": []}

    for z in zonas_raw:
        zona_id, zona_nombre, cat = z["id"], z["nombre"], z["categoria"]

        cursor.execute("SELECT * FROM jugadores WHERE zona_id = ? ORDER BY id", (zona_id,))
        jugadores = [dict(j) for j in cursor.fetchall()]

        cursor.execute("SELECT * FROM partidos WHERE zona_id = ?", (zona_id,))
        partidos_raw = cursor.fetchall()

        matriz_resultados = {}
        for p in partidos_raw:
            j1, j2, res_txt = p["jugador1_id"], p["jugador2_id"], p["resultado_texto"]
            if j1 not in matriz_resultados: matriz_resultados[j1] = {}
            if j2 not in matriz_resultados: matriz_resultados[j2] = {}

            matriz_resultados[j1][j2] = {
                "sets_prop": p["sets_ganados1"], "sets_riva": p["sets_ganados2"],
                "games_prop": p["games_totales1"], "games_riva": p["games_totales2"],
                "sets_list": parse_sets_para_vista(res_txt),
            }

            set_tokens = [s.strip() for s in res_txt.split(",") if s.strip()]
            inverted_tokens = [f"{t.split('-')[1].strip()}-{t.split('-')[0].strip()}" if "-" in t else t for t in
                               set_tokens]
            res_txt_inv = ", ".join(inverted_tokens)

            matriz_resultados[j2][j1] = {
                "sets_prop": p["sets_ganados2"], "sets_riva": p["sets_ganados1"],
                "games_prop": p["games_totales2"], "games_riva": p["games_totales1"],
                "sets_list": parse_sets_para_vista(res_txt_inv),
            }

        stats = {}
        for j in jugadores:
            j_id = j["id"]
            stats[j_id] = {"id": j_id, "nombre": j["nombre"], "pg": 0, "sf": 0, "sc": 0, "gf": 0, "gc": 0,
                           "pct_sets": 0.0, "pct_games": 0.0}
            if j_id in matriz_resultados:
                for rival_id, res in matriz_resultados[j_id].items():
                    stats[j_id]["sf"] += res["sets_prop"]
                    stats[j_id]["sc"] += res["sets_riva"]
                    stats[j_id]["gf"] += res["games_prop"]
                    stats[j_id]["gc"] += res["games_riva"]
                    if res["sets_prop"] > res["sets_riva"]: stats[j_id]["pg"] += 1

            tot_sets = stats[j_id]["sf"] + stats[j_id]["sc"]
            if tot_sets > 0: stats[j_id]["pct_sets"] = round((stats[j_id]["sf"] / tot_sets) * 100, 1)

            tot_games = stats[j_id]["gf"] + stats[j_id]["gc"]
            if tot_games > 0: stats[j_id]["pct_games"] = round((stats[j_id]["gf"] / tot_games) * 100, 1)

        lista_ordenada = sorted(list(stats.values()), key=lambda x: (x["pg"], x["pct_sets"], x["pct_games"]),
                                reverse=True)
        posiciones_map = {st["id"]: rank for rank, st in enumerate(lista_ordenada, start=1)}

        zona_obj = {
            "id": zona_id, "nombre": zona_nombre, "categoria": cat,
            "jugadores": jugadores, "matriz": matriz_resultados,
            "stats": stats, "posiciones": posiciones_map,
        }

        if cat in categorias_data:
            categorias_data[cat].append(zona_obj)
        else:
            categorias_data["3era"].append(zona_obj)

    # Obtener los datos del cuadro de eliminación
    cursor.execute("SELECT * FROM cuadros ORDER BY categoria, id")
    cuadros_raw = [dict(c) for c in cursor.fetchall()]

    cuadros_data = {"3era": {"cuartos": [], "semi": [], "final": []}, "4ta": {"cuartos": [], "semi": [], "final": []}}
    for c in cuadros_raw:
        cuadros_data[c["categoria"]][c["instancia"]].append(c)

    return categorias_data, cuadros_data


@app.route("/")
def index():
    categorias, cuadros = obtener_datos_torneo()
    return render_template("index.html", categorias=categorias, cuadros=cuadros, es_admin=False)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        pwd = request.form.get("password")
        if pwd == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))

    es_admin = session.get("admin_logged_in", False)
    categorias, cuadros = obtener_datos_torneo()
    return render_template("index.html", categorias=categorias, cuadros=cuadros, es_admin=es_admin)


@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("index"))


@app.route("/crear_zona", methods=["POST"])
def crear_zona():
    if not session.get("admin_logged_in"): return redirect(url_for("index"))
    nombre, categoria = request.form.get("nombre_zona"), request.form.get("categoria_zona")
    if nombre and categoria:
        db = get_db()
        db.cursor().execute("INSERT INTO zonas (nombre, categoria) VALUES (?, ?)", (nombre.strip(), categoria))
        db.commit()
    return redirect(url_for("admin"))


@app.route("/crear_jugador", methods=["POST"])
def crear_jugador():
    if not session.get("admin_logged_in"): return redirect(url_for("index"))
    nombre, zona_id = request.form.get("nombre_jugador"), request.form.get("zona_id")
    if nombre and zona_id:
        db = get_db()
        db.cursor().execute("INSERT INTO jugadores (nombre, zona_id) VALUES (?, ?)", (nombre.strip(), int(zona_id)))
        db.commit()
    return redirect(url_for("admin"))


@app.route("/cargar_partido", methods=["POST"])
def cargar_partido():
    if not session.get("admin_logged_in"): return redirect(url_for("index"))
    zona_id = int(request.form.get("zona_id"))
    j1_id, j2_id = int(request.form.get("jugador1_id")), int(request.form.get("jugador2_id"))

    if j1_id != j2_id:
        sets_list = [
            (request.form.get("set1_j1", type=int, default=0), request.form.get("set1_j2", type=int, default=0)),
            (request.form.get("set2_j1", type=int, default=0), request.form.get("set2_j2", type=int, default=0)),
            (request.form.get("set3_j1", type=int, default=0), request.form.get("set3_j2", type=int, default=0))
        ]
        texto_sets, sets_g1, sets_g2, games_t1, games_t2 = [], 0, 0, 0, 0
        for g1, g2 in sets_list:
            if g1 > 0 or g2 > 0:
                texto_sets.append(f"{g1}-{g2}")
                games_t1 += g1
                games_t2 += g2
                if g1 > g2:
                    sets_g1 += 1
                elif g2 > g1:
                    sets_g2 += 1

        resultado_texto = ", ".join(texto_sets)
        p1, p2 = (j1_id, j2_id) if j1_id < j2_id else (j2_id, j1_id)

        if j1_id == p1:
            res_final, sg1, sg2, gt1, gt2 = resultado_texto, sets_g1, sets_g2, games_t1, games_t2
        else:
            res_final = ", ".join([f"{t.split('-')[1]}-{t.split('-')[0]}" for t in texto_sets])
            sg1, sg2, gt1, gt2 = sets_g2, sets_g1, games_t2, games_t1

        db = get_db()
        db.cursor().execute("""
            INSERT INTO partidos (zona_id, jugador1_id, jugador2_id, resultado_texto, sets_ganados1, sets_ganados2, games_totales1, games_totales2)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(zona_id, jugador1_id, jugador2_id) DO UPDATE SET
                resultado_texto=excluded.resultado_texto, sets_ganados1=excluded.sets_ganados1,
                sets_ganados2=excluded.sets_ganados2, games_totales1=excluded.games_totales1, games_totales2=excluded.games_totales2
        """, (zona_id, p1, p2, res_final, sg1, sg2, gt1, gt2))
        db.commit()
    return redirect(url_for("admin"))


# Endpoint para actualizar partidos del cuadro eliminatorio
@app.route("/actualizar_cuadro", methods=["POST"])
def actualizar_cuadro():
    if not session.get("admin_logged_in"): return redirect(url_for("index"))
    cuadro_id = request.form.get("cuadro_id", type=int)
    j1_nombre = request.form.get("jugador1_nombre", "").strip()
    j2_nombre = request.form.get("jugador2_nombre", "").strip()
    resultado = request.form.get("resultado", "").strip()

    if cuadro_id:
        db = get_db()
        db.cursor().execute("""
            UPDATE cuadros 
            SET jugador1_nombre = ?, jugador2_nombre = ?, resultado = ?
            WHERE id = ?
        """, (j1_nombre, j2_nombre, resultado, cuadro_id))
        db.commit()

    return redirect(url_for("admin"))


@app.route("/eliminar_jugador/<int:jugador_id>", methods=["POST"])
def eliminar_jugador(jugador_id):
    if not session.get("admin_logged_in"): return redirect(url_for("index"))
    db = get_db()
    db.cursor().execute("DELETE FROM jugadores WHERE id = ?", (jugador_id,))
    db.cursor().execute("DELETE FROM partidos WHERE jugador1_id = ? OR jugador2_id = ?", (jugador_id, jugador_id))
    db.commit()
    return redirect(url_for("admin"))


@app.route("/eliminar_zona/<int:zona_id>", methods=["POST"])
def eliminar_zona(zona_id):
    if not session.get("admin_logged_in"): return redirect(url_for("index"))
    db = get_db()
    db.cursor().execute("DELETE FROM zonas WHERE id = ?", (zona_id,))
    db.commit()
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(debug=True)