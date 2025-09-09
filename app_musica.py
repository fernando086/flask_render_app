import subprocess, base64
from flask import Flask, Response, request, jsonify
import flask
from flask_compress import Compress
import psycopg2
from psycopg2 import Binary
from psycopg2.extras import RealDictCursor
import firebase_admin
from firebase_admin import credentials, auth
from datetime import datetime, time, timedelta
from pydub import AudioSegment

import torch
import torch.nn as nn
import torchaudio
import librosa
import numpy as np
import io

import re
import os
import json
import urllib.request

active_downloads = {}  # Diccionario para rastrear descargas en curso

app = Flask(__name__)
Compress(app)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

# Inicializar Firebase Admin SDK
firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
cred = credentials.Certificate(json.loads(firebase_credentials))
firebase_admin.initialize_app(cred)

@app.route('/')
def index():
    return "Servidor Flask funcionando correctamente."

@app.route('/api/token', methods=['POST'])
def receive_token():
    # Aquí recibimos el token del cliente
    data = request.json
    if 'token' in data:
        token = data['token']
        # Aquí puedes visualizar el token en la consola del servidor
        print(f"Token recibido: {token}")
        # Procesar el token como desees
        return jsonify({"message": "Token recibido exitosamente"}), 200
    else:
        return jsonify({"error": "Token no encontrado"}), 400

@app.route('/api/verify_token', methods=['POST'])
def verify_token():
    token = request.json.get('token')

    try:
        # Verificar el token recibido
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
        print("Token válido.")
        return jsonify({"message": "Token válido", "user_id": uid}), 200
    except Exception as e:
        print(f"Error de verificación del token: {str(e)}")
        return jsonify({"message": "Token no válido", "error": str(e)}), 401

@app.route('/protected', methods=['POST'])
def protected_route():
    id_token = request.headers.get('Authorization')
    user_id = verify_token(id_token)
    if user_id:
        return jsonify({"message": "Token válido, acceso permitido"})
    else:
        return jsonify({"message": "Token inválido o ausente"}), 401

''' PARA BASE DE DATOS LOCAL, ES DECIR, SIN RENDER
def get_db_connection():
    conn = psycopg2.connect(
        host="localhost",
        database="intento_aplicacionmovil_android",
        user="admin_fernando",
        password="191VP90957QX2685",
        port="5433"
    )
    return conn
'''
# PARA BASE DE DATOS REAL, ES DECIR, CON RENDER
def get_db_connection():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    return conn

@app.route('/usuarios')
def get_usuarios():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM usuario')
    usuario = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(usuario)

# Función para agregar un usuario a PostgreSQL si no existe
def agregar_usuario_si_no_existe(nombre, uid):
    try:
        # Conexión a PostgreSQL
        '''conn = psycopg2.connect(
            host="localhost",
            database="intento_aplicacionmovil_android",  # Cambia el nombre de tu base de datos
            user="admin_fernando",  # Cambia por tu usuario de PostgreSQL
            password="191VP90957QX2685"  # Cambia por tu contraseña de PostgreSQL
        )'''
        conn = get_db_connection()
        cursor = conn.cursor()        

        # Verificar si el usuario ya existe por el UID de Firebase
        cursor.execute("SELECT id FROM Usuario WHERE firebase_uid = %s", (uid,))
        resultado = cursor.fetchone()

        if resultado is None:
            # Si no existe, insertar un nuevo usuario
            cursor.execute(
                "INSERT INTO Usuario (nombre, firebase_uid) VALUES (%s, %s) RETURNING id",
                (nombre, uid)
            )
            usuario_id = cursor.fetchone()[0]
            conn.commit()
            print(f"Usuario nuevo agregado con ID {usuario_id}")
            return jsonify({"message": "Usuario nuevo agregado", "user_id": usuario_id}), 200
        else:
            print("El usuario ya existe en la base de datos: ", resultado)
            return jsonify({"message": "Usuario ya existente", "user_id": resultado[0]}), 200        

    except Exception as e:
        print(f"Error al agregar o verificar usuario: {e}")
    cursor.close()
    conn.close()

@app.route('/api/get_user', methods=['POST'])
def get_user():
    token = request.json.get('token')

    try:
        # Verificar el token
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']

        # Conectar a PostgreSQL
        '''conn = psycopg2.connect(
            host="localhost",
            database="intento_aplicacionmovil_android",  # Cambia el nombre de tu base de datos
            user="admin_fernando",  # Cambia por tu usuario de PostgreSQL
            password="191VP90957QX2685"  # Cambia por tu contraseña de PostgreSQL
        )'''
        conn = get_db_connection()
        cursor = conn.cursor()

        # Buscar al usuario por su ID de Firebase
        cursor.execute("SELECT nombre, imagen FROM Usuario WHERE id_firebase = %s", (uid,))
        user = cursor.fetchone()

        if user:
            nombre, imagen = user
            return jsonify({
                "nombre": nombre,
                "imagen": imagen.decode('utf-8') if imagen else None
            }), 200
        else:
            return jsonify({"message": "Usuario no encontrado"}), 404
    except Exception as e:
        return jsonify({"message": "Error al obtener usuario", "error": str(e)}), 400
    finally:
        cursor.close()
        conn.close()

@app.route('/api/verificar_o_guardar_usuario', methods=['POST'])
def verificar_o_guardar_usuario():
    data = request.get_json()
    print("Datos recibidos:", data) # Recibidos desde Android Studio
    nombre = data.get('nombre')
    imagen = data.get('imagen')  # Aquí estará la URL o el byte array según cómo lo manejes
    firebase_uid = data.get('firebaseUid')

    conn = None
    cursor = None

    print(f"Firebase UID recibido: {firebase_uid}")  # Depuración
    print(f"Nombre recibido: {nombre}")
    print(f"Imagen recibida: {imagen}")

    if not firebase_uid:
        print("Error: Firebase UID no proporcionado.")
        return jsonify({"error": "Firebase UID no proporcionado"}), 400

    try:
        print("estableciendo conexión con BD PostgreSQL")
        '''conn = psycopg2.connect(
            host="localhost",
            database="intento_aplicacionmovil_android",
            user="admin_fernando",
            password="191VP90957QX2685",
            port="5433"
        )'''
        conn = get_db_connection()
        print("el usuario que se conectará a la base de datos ha sido identificado")
        cursor = conn.cursor()
        print("cursor conectado")

        # Verificar si el usuario ya existe en la base de datos
        cursor.execute("SELECT * FROM usuario WHERE firebase_uid = %s", (firebase_uid,))
        print("cursor ejecutado")
        usuario = cursor.fetchone()
        print("buscando si existe el usuario")

        if usuario:
            print("Usuario ya existente: ", usuario[0]) # TODO ENVIAR ESTE NÚMERO HACIA ANDROID STUDIO, O ENVIAR FIREBASE UID DESDE MENUPRINCIPAL HACIA OTRA INTERFAZ
        else:
            # Insertar el nuevo usuario en la base de datos
            print("el usuario no existe, insertando")
            cursor.execute("""
                INSERT INTO Usuario (nombre, imagen, firebase_uid)
                VALUES (%s, %s, %s)
            """, (nombre, imagen, firebase_uid))
            conn.commit()
            print(f"Nuevo usuario insertado en PostgreSQL: {nombre}")

        return jsonify({"message": "Operación exitosa"}), 200

    except Exception as e:
        print(f"Error al agregar o verificar usuario: {str(e)}")
        return jsonify({"error": f"Error al agregar o verificar usuario: {str(e)}"}), 500

    finally:
        # Asegurarse de cerrar el cursor y la conexión
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/obtener_datos_usuario', methods=['POST'])
def obtener_datos_usuario():
    data = request.get_json()
    firebase_uid = data.get('firebaseUid')

    conn = None
    cursor = None

    if not firebase_uid:
        return jsonify({"error": "Firebase UID no proporcionado"}), 400

    try:
        '''conn = psycopg2.connect(
            host="localhost",
            database="intento_aplicacionmovil_android",
            user="admin_fernando",
            password="191VP90957QX2685",
            port="5433"
        )'''
        conn = get_db_connection()
        cursor = conn.cursor()

        # Obtener los datos del usuario desde la base de datos
        cursor.execute("SELECT id, nombre, imagen, firebase_uid FROM usuario WHERE firebase_uid = %s", (firebase_uid,))
        usuario = cursor.fetchone()

        if usuario:
            user_id, user_name, user_image, user_firebase_uid = usuario
            return jsonify({
                "id": user_id,
                "nombre": user_name,
                "imagen": user_image,
                "firebaseUid": user_firebase_uid
            }), 200
        else:
            return jsonify({"error": "Usuario no encontrado"}), 404

    except Exception as e:
        return jsonify({"error": f"Error al obtener datos del usuario: {str(e)}"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route('/api/update_username', methods=['PUT'])
def update_username():
    print("consiguiendo data")
    data = request.json
    new_name = data.get('newName')
    user_token = request.headers.get('Authorization')
    print("newName = ", new_name, " Authorization = ", user_token)

    # Remover el prefijo 'Bearer ' si está presente
    if user_token.startswith("Bearer "):
        user_token = user_token.split(" ")[1]

    try:
        # Verificar el token y obtener el firebase_uid
        decoded_token = auth.verify_id_token(user_token)
        firebase_uid = decoded_token['uid']
        print("Firebase UID: ", firebase_uid)
    except Exception as e:
        print("Error al verificar el token: ", str(e))
        return jsonify({'error': 'Token inválido'}), 401

    # Obtener conexión y cursor
    conn = get_db_connection()
    print("conexión a postgresql conseguida")
    cur = conn.cursor()
    print("cursor para postgresql conectado")

    # Busca al usuario en la base de datos por el firebase_uid (que asumo se corresponde con el token)
    cur.execute("SELECT id, last_name_change FROM usuario WHERE firebase_uid = %s", (firebase_uid,))
    print("el select se ha ejecutado")
    user = cur.fetchone()
    print("se ejecutó fetchone")
    print("entrando a if else")

    if user:
        user_id, last_name_change = user

        # Verifica si ha pasado al menos 24 horas desde el último cambio de nombre
        now = datetime.now()
        if last_name_change and now - last_name_change < timedelta(hours=24):
            cur.close()
            conn.close()
            print("El usuario intentó cambiar su nombre antes del plazo de 24 horas.")
            return jsonify({'error': 'You can only change your name once every 24 hours'}), 403

        # Actualiza el nombre y el tiempo de cambio
        cur.execute("UPDATE usuario SET nombre = %s, last_name_change = %s WHERE id = %s",
                    (new_name, now, user_id))
        conn.commit()

        cur.close()
        conn.close()
        return jsonify({'success': True, 'name': new_name}), 200
    else:
        cur.close()
        conn.close()
        return jsonify({'error': 'User not found'}), 404

@app.route('/api/obtener_canciones', methods=['GET'])
def obtener_canciones():
    usuario_id = request.args.get('usuario_id')
    print("obtener_canciones: El valor de usuario_id conseguido es: ", usuario_id)

    if not usuario_id:
        return jsonify({"error": "Falta user_id"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
            SELECT c.id, c.nombre, c.autor, c.album, c.enlace,
                   c.comentario_general, c.estado_cg_publicado, c.estado_publicado,
                   c.fecha_creacion, c.fecha_ultima_edicion
            FROM cancion c
            INNER JOIN usuario u ON c.usuario_id = u.id
            WHERE u.firebase_uid = %s
        """
        cursor.execute(query, (usuario_id,))
        canciones = cursor.fetchall()

        canciones_list = []
        archivo_contenido = []

        for cancion in canciones:
            cancion_id = cancion[0]

            cursor.execute("""
                SELECT s.id, s.tiempo_inicio, s.tiempo_final, s.fecha_creacion, s.fecha_ultima_edicion,
                       s.nombre, s.comentario_seccion, s.estado_cs_publicado
                FROM seccion s
                WHERE s.cancion_id = %s
                ORDER BY s.tiempo_inicio
            """, (cancion_id,))
            secciones = cursor.fetchall()

            secciones_list = []
            secciones_str_partes = []

            for s in secciones:
                seccion_id = s[0]

                # Emociones
                cursor.execute("SELECT palabra FROM emocion_seleccionada WHERE seccion_id = %s", (seccion_id,))
                emociones = [row[0] for row in cursor.fetchall()]

                # Géneros
                cursor.execute("""
                    SELECT g.id, g.nombre
                    FROM seccion_genero sg
                    JOIN genero g ON sg.genero_id = g.id
                    WHERE sg.seccion_id = %s
                """, (seccion_id,))
                generos = [{"id": row[0], "nombre_genero": row[1]} for row in cursor.fetchall()]

                # Serializar para JSON principal
                tiempo_inicio_str = s[1].strftime("%M:%S.%f")[:-3]
                tiempo_fin_str = s[2].strftime("%M:%S.%f")[:-3]
                f_creacion = s[3].strftime("%Y-%m-%d %H:%M:%S.%f")
                f_ultima_edicion = s[4].strftime("%Y-%m-%d %H:%M:%S.%f")
                secciones_list.append({
                    "id": seccion_id,
                    "inicio": tiempo_inicio_str,
                    "fin": tiempo_fin_str,
                    "s_f_creacion": f_creacion,
                    "s_f_ultima_edicion": f_ultima_edicion,
                    "nombre_seccion": s[5],
                    "comentario": s[6],
                    "publicado": s[7],
                    "emociones": emociones,
                    "generos": generos
                })

                # Serializar para archivo local
                seccion_str = "{}-{}/{}//{}//{}//{}//{}//{}//{}".format(
                    seccion_id,
                    tiempo_inicio_str,
                    tiempo_fin_str,
                    f_creacion,
                    f_ultima_edicion,
                    s[5] or "",
                    s[6] or "",
                    s[7],
                    ",".join(emociones),
                    ",".join([g["nombre_genero"] for g in generos])
                )
                secciones_str_partes.append(seccion_str)

            canciones_list.append({
                "id": cancion_id,
                "nombre": cancion[1],
                "autor": cancion[2],
                "album": cancion[3],
                "enlace": cancion[4],
                "comentario_general": cancion[5],
                "estado_cg_publicado": cancion[6],
                "estado_publicado": cancion[7],
                "f_creacion": cancion[8].strftime("%Y-%m-%d %H:%M:%S.%f"),
                "f_ultima_edicion": cancion[9].strftime("%Y-%m-%d %H:%M:%S.%f"),
                "secciones": secciones_list
            })

            archivo_contenido.append(f"{cancion_id};{cancion[1]};{cancion[2]};{cancion[3]};{cancion[4]};{cancion[5]};{cancion[6]};{cancion[7]};{cancion[8]};{cancion[9]};{'|'.join(secciones_str_partes)}\n")

        cursor.close()
        conn.close()

        return jsonify({
            "canciones": canciones_list,
            "archivo_contenido": archivo_contenido
        }), 200

    except Exception as e:
        import traceback
        print("⚠️ Error en obtener_canciones:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_archivo', methods=['POST'])
def get_archivo():
    try:
        data = request.get_json()
        cancion_id = data.get('cancion_id')

        if not cancion_id:
            return jsonify({"error": "ID de canción no proporcionado"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT archivo FROM cancion WHERE id = %s", (cancion_id,))
        resultado = cursor.fetchone()

        cursor.close()
        conn.close()

        if resultado and resultado[0]:
            archivo_bytes = resultado[0]
            return Response(archivo_bytes, mimetype="audio/mpeg")
        else:
            return jsonify({"error": "Archivo no encontrado"}), 404

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def descargar_audio_yield(enlace):
    """Descarga el audio desde YouTube y transmite directamente al usuario."""
    comando = [
        "yt-dlp", "-f", "bestaudio", "--extract-audio",
        "--audio-format", "mp3", "--output", "-", enlace
    ]

    proceso = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def generar():
        while True:
            chunk = proceso.stdout.read(8192)  # Lee en bloques de 8KB
            if not chunk:
                break
            yield chunk  # Se envía directamente al usuario
    
    return flask.stream_with_context(generar())

@app.route('/api/get_audio', methods=['POST'])
def get_audio():
    enlace = request.json.get('songEnlace')
    return Response(descargar_audio_yield(enlace), mimetype="audio/mpeg")

@app.route('/api/get_secciones', methods=['GET'])
def get_secciones():
    try:
        cancion_id = request.args.get('cancion_id')  # Obtener el ID de la canción desde la solicitud

        if not cancion_id:
            return jsonify({"error": "Se requiere el ID de la canción"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        query = """
        SELECT id, tiempo_inicio, tiempo_final, fecha_creacion, fecha_ultima_edicion
        FROM seccion
        WHERE cancion_id = %s
        ORDER BY tiempo_inicio ASC;
        """
        print("get_secciones dice: query listo")
        cursor.execute(query, (cancion_id,))
        secciones = cursor.fetchall()
        print("get_secciones dice: fetch all listo")
        cursor.close()
        conn.close()

        # Convertir los resultados en una lista de diccionarios
        lista_secciones = []
        print("get_secciones dice: lista secciones [] listo")
        for seccion in secciones:
            lista_secciones.append({
                "id": seccion[0],
                #"cancion_id": seccion[1], # No es necesario este campo porque ya está entrando desde menu hacia datosM
                #"usuario_id": seccion[2], # De igual manera con el anterior campo
                "tiempo_inicio": seccion[1].strftime("%M:%S.%f")[:-3],  # 🔹 Convertir a String (ejemplo: "01:56.810")
                "tiempo_final": seccion[2].strftime("%M:%S.%f")[:-3],   # 🔹 Convertir a String (ejemplo: "02:09.850")
                "fecha_creacion": seccion[3].strftime("%Y-%m-%d %H:%M:%S.%f"),
                "fecha_ultima_edicion": seccion[4].strftime("%Y-%m-%d %H:%M:%S.%f")
                #"id_orden_seccion": seccion[3] # Se podría generar automáticamente en el código de Android Studio
            })

        print("get_secciones dice: método correcto")
        print(lista_secciones)
        return jsonify({"secciones": lista_secciones}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def procesar_audio_desde_enlace(enlace):
    # Paso 1: usar yt-dlp para obtener el mejor audio, en formato original
    ytdlp_cmd = [
        "yt-dlp", "-f", "bestaudio", "-o", "-", enlace
    ]
    
    # Paso 2: pasarlo a ffmpeg para convertirlo a WAV (más seguro para procesamiento)
    ffmpeg_cmd = [
        "ffmpeg", "-i", "pipe:0",
        "-f", "wav", "pipe:1"
    ]
    
    ytdlp_proc = subprocess.Popen(ytdlp_cmd, stdout=subprocess.PIPE)
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=ytdlp_proc.stdout, stdout=subprocess.PIPE)

    audio_data = ffmpeg_proc.stdout.read()
    ffmpeg_proc.wait()
    ytdlp_proc.wait()

    if ffmpeg_proc.returncode != 0 or ytdlp_proc.returncode != 0:
        raise Exception("Error al descargar o convertir audio.")

    # Paso 3: procesar audio con la misma función que ya usas en /api/predecir_emociones
    mel_tensor, lengths = procesar_audio(audio_data)  # usa la función que ya tienes definida

    # Paso 4: inferencia con tu modelo
    with torch.no_grad():
        salida = model(mel_tensor, lengths)
        salida_prom = salida.mean(dim=1)  # promedio en el tiempo

    arousal = float(salida_prom[0][0].item())
    valence = float(salida_prom[0][1].item())
    print(f"Predicción -> Valence: {valence:.4f}, Arousal: {arousal:.4f}")

    return valence, arousal
    
@app.route('/api/subir_enlace', methods=['POST'])
def subir_enlace():
    enlace = request.form.get('enlace')
    usuario_id = request.form.get('usuario_id')

    if not enlace or not usuario_id:
        return jsonify({"error": "Faltan datos"}), 400

    try:
        import yt_dlp
        import datetime

        # Extraer información usando yt-dlp
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'forcejson': True,
            'extract_flat': False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(enlace, download=False)

        nombre = info.get('title', '')
        print("subir_enlace: titulo de enlace youtube: ", nombre)
        autor = info.get('uploader', '')
        album = info.get('album', None)
        duracion_segundos = info.get('duration', 0)
        duracion_time = str(datetime.timedelta(seconds=duracion_segundos))  # HH:MM:SS

        # 🔹 Procesar audio desde stream y obtener valence/arousal
        valence, arousal = procesar_audio_desde_enlace(enlace)

        print("ENLACE EXTRAÍDO:", nombre, autor, album, duracion_time)

        # Conexión a la base de datos
        conn = get_db_connection()
        cursor = conn.cursor()
        print("subir_enlace: ejecutando cursor")
        cursor.execute("""
            SELECT * FROM insertar_cancion_con_seccion(%s, %s, %s, %s, %s, NULL, false, NULL, %s)
        """, (
            int(usuario_id), nombre, autor, album, enlace, duracion_time
        ))
        resultado = cursor.fetchone()
        print("subir_enlace: cursor ejecutado")
        nueva_cancion_id = resultado[0]
        fecha_creacion = resultado[1].strftime("%Y-%m-%d %H:%M:%S.%f")
        fecha_ultima_edicion = resultado[2].strftime("%Y-%m-%d %H:%M:%S.%f")
        id_seccion = resultado[3]
        fecha_creacion_seccion = resultado[4].strftime("%Y-%m-%d %H:%M:%S.%f")
        fecha_ultima_edicion_seccion = resultado[5].strftime("%Y-%m-%d %H:%M:%S.%f")

        print(nueva_cancion_id)
        print(fecha_creacion)
        print(fecha_ultima_edicion)
        print(id_seccion)
        print(fecha_creacion_seccion)
        print(fecha_ultima_edicion_seccion)

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "mensaje": "Enlace subido exitosamente",
            "id": nueva_cancion_id,
            "nombre": nombre,
            "autor": autor,
            "album": album,
            "duracion": duracion_time,
            "fecha_creacion": fecha_creacion,
            "fecha_ultima_edicion": fecha_ultima_edicion,
            "id_seccion": id_seccion,
            "fecha_creacion_seccion": fecha_creacion_seccion,
            "fecha_ultima_edicion_seccion": fecha_ultima_edicion_seccion,
            "valence": valence,
            "arousal": arousal
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
#TODO
@app.route('/api/subir_audio', methods=['POST'])
def subir_audio():
    if 'archivo' not in request.files:
        return jsonify({"error": "No se envió ningún archivo"}), 400

    archivo = request.files['archivo']
    usuario_id = request.form.get('usuario_id')
    nombre = request.form.get('nombre')
    nombre_sin_extension = re.sub(r'\.(mp3|wav|ogg)$', '', nombre, flags=re.IGNORECASE)
    duracion = request.form.get('tiempo_fin')  # ejemplo: "00:06:48"
    print("subir_audio: duracion = ", duracion)

    duracion_obj = validar_formato_tiempo(duracion)
    
    if not duracion_obj:
        print('DURACIÓN CON FORMATO INVÁLIDO')
        return jsonify({"error": "Formato de duración inválido. Debe ser HH:MM:SS"}), 400
    
    duracion_str = duracion_obj.strftime('%H:%M:%S.%f')[:-3]  # "00:01:58.299"

    if not usuario_id:
        return jsonify({"error": "No se envió usuario_id"}), 400

    if archivo.filename == '':
        return jsonify({"error": "Nombre de archivo inválido"}), 400

    if not allowed_file(archivo.filename):
        return jsonify({"error": "Formato de archivo no permitido"}), 400

    if not archivo.mimetype.startswith('audio/'):
        return jsonify({"error": "Solo se permiten archivos de audio"}), 400
    
    contenido_bytes = archivo.read()

    # Procesar y predecir emociones
    mel_tensor, lengths = procesar_audio(contenido_bytes)

    with torch.no_grad():
        salida = model(mel_tensor, lengths)  # salida: [batch, seq_len, 2]
        salida_prom = salida.mean(dim=1)     # ahora: [batch, 2]

    arousal = float(salida_prom[0][0].item()) # Línea 709
    valence = float(salida_prom[0][1].item())

    print(f"[Predicción] Arousal: {arousal:.4f}, Valence: {valence:.4f}")

    # Aquí debes guardar en PostgreSQL
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        print("subir_audio: usuario: ", usuario_id)
        print("subir_audio: ejecutando select para insertar audio")
        cursor.execute("""
        SELECT * FROM insertar_cancion_con_seccion(%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            int(usuario_id),     # p_usuario_id
            nombre_sin_extension,# p_nombre
            None,                # p_autor
            None,                # p_album
            nombre,              # p_enlace
            None,                # p_comentario_general
            False,               # p_estado_cg_publicado
            psycopg2.Binary(contenido_bytes),  # p_archivo
            duracion_str         # p_duracion
        ))
        print("select ejecutado")
        resultado = cursor.fetchone()
        nueva_cancion_id = resultado[0]
        fecha_creacion = resultado[1].strftime("%Y-%m-%d %H:%M:%S.%f")
        fecha_ultima_edicion = resultado[2].strftime("%Y-%m-%d %H:%M:%S.%f")
        id_seccion = resultado[3]
        fecha_creacion_seccion = resultado[4].strftime("%Y-%m-%d %H:%M:%S.%f")
        fecha_ultima_edicion_seccion = resultado[5].strftime("%Y-%m-%d %H:%M:%S.%f")

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "mensaje": "Archivo subido exitosamente",
            "id": nueva_cancion_id,
            "fecha_creacion": fecha_creacion,
            "fecha_ultima_edicion": fecha_ultima_edicion,
            "id_seccion": id_seccion,
            "fecha_creacion_seccion": fecha_creacion_seccion,
            "fecha_ultima_edicion_seccion": fecha_ultima_edicion_seccion
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg'}

def validar_formato_tiempo(tiempo_str):
    # Aceptar formatos como "00:06:48" o "00:06:48.299"
    match = re.match(r'^(\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?$', tiempo_str)
    if not match:
        return None

    h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
    microsegundos = int(float(match.group(4) or 0) * 1_000_000)

    try:
        return time(hour=h, minute=m, second=s, microsecond=microsegundos)
    except:
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ====== Cargar modelo una sola vez al inicio ======
import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

class CNN2D_BiLSTM(nn.Module):
    def __init__(self, n_mels=128, cnn_out_channels=64, lstm_hidden=128, lstm_layers=2):
        super(CNN2D_BiLSTM, self).__init__()

        # Bloque CNN 2D
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=(3,3), padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d((2,2)),

            nn.Conv2d(32, cnn_out_channels, kernel_size=(3,3), padding=1),
            nn.BatchNorm2d(cnn_out_channels),
            nn.ReLU(),
            nn.MaxPool2d((2,2)),

            nn.AdaptiveAvgPool2d((4, 8))
        )

        # Calcular tamaño tras la CNN para LSTM
        example_input = torch.zeros(1, 1, n_mels, 130)
        with torch.no_grad():
            cnn_out = self.cnn(example_input)
        cnn_out_size = cnn_out.shape[1] * cnn_out.shape[2] * cnn_out.shape[3]

        # LSTM bidireccional
        self.lstm = nn.LSTM(
            input_size=cnn_out_size,
            hidden_size=lstm_hidden,
            num_layers=lstm_layers,
            batch_first=True,
            bidirectional=True
        )

        # Capa final
        self.fc = nn.Linear(lstm_hidden*2, 2)

    def forward(self, x, lengths):
        batch, windows, ch, mel, time = x.shape
        x = x.reshape(batch * windows, ch, mel, time)
        x = self.cnn(x)
        x = x.view(x.size(0), -1)
        x = x.reshape(batch, windows, -1)

        lengths_cpu = lengths.cpu()
        packed = pack_padded_sequence(x, lengths_cpu, batch_first=True, enforce_sorted=False)
        packed_out, _ = self.lstm(packed)
        out, _ = pad_packed_sequence(packed_out, batch_first=True)

        out = self.fc(out)
        return out

# Crear el modelo y cargar pesos
# Ruta local donde se guardará el modelo en Render
MODEL_DIR = "models_oficial"
MODEL_PATH = os.path.join(MODEL_DIR, "cnn2d_bilstm_deam.pth")

# URL pública de tu modelo en Google Drive
# IMPORTANTE: Debes generar un enlace de descarga directa
# Ejemplo: https://drive.google.com/uc?export=download&id=TU_ID_DE_ARCHIVO
# El enlace obtenido al compartir un archivo tiene un ID, en este caso es: 1yf5M1aZZsOnNCDQYciWcJp_qNQzBmNU9
# Pero se necesita un enlace que permita convertir el archivo en un descargable directo:
MODEL_URL = "https://drive.google.com/uc?export=download&id=1yf5M1aZZsOnNCDQYciWcJp_qNQzBmNU9"

# Si el archivo no existe, lo descarga
if not os.path.exists(MODEL_PATH):
    os.makedirs(MODEL_DIR, exist_ok=True)
    print("Descargando modelo desde Google Drive...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("Modelo descargado correctamente!")

# Cargar modelo
model = CNN2D_BiLSTM(n_mels=128)
model.load_state_dict(torch.load(MODEL_PATH, map_location=torch.device('cpu')))
model.eval()

# ====== Función para preprocesar audio ======
def procesar_audio(file_bytes):
    y, sr = librosa.load(io.BytesIO(file_bytes), sr=22050, mono=True)
    mel_spec = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128)
    mel_db = librosa.power_to_db(mel_spec, ref=np.max)
    mel_norm = (mel_db - mel_db.mean()) / (mel_db.std() + 1e-9)

    # Ajustar forma: batch=1, windows=1, channel=1, mel_bins, time_steps
    mel_tensor = torch.tensor(mel_norm, dtype=torch.float32).unsqueeze(0).unsqueeze(0).unsqueeze(0)

    # Longitudes reales (aquí solo hay 1 ventana)
    lengths = torch.tensor([1])

    return mel_tensor, lengths

# ====== Nuevo endpoint ======
@app.route("/api/predecir_emociones", methods=["POST"])
def predecir_emociones():
    if 'archivo' not in request.files:
        return jsonify({"error": "No se envió archivo"}), 400

    archivo = request.files['archivo']
    audio_bytes = archivo.read()

    # Preprocesar
    mel_tensor, lengths = procesar_audio(audio_bytes)

    # Inferencia
    with torch.no_grad():
        salida = model(mel_tensor, lengths)
        salida_prom = salida.mean(dim=1)

    arousal = float(salida_prom[0][0].item())
    valence = float(salida_prom[0][1].item())

    # Mostrar en consola (CMD)
    print(f"[Predicción] Arousal: {arousal:.4f}, Valence: {valence:.4f}")

    # Responder a la app
    return jsonify({
        "arousal": arousal,
        "valence": valence
    }), 200

@app.route('/api/actualizar_cancion', methods=['POST'])
def actualizar_cancion():
    try:
        data = request.get_json()
        song_id = data.get('song_id')
        nombre = data.get('nombre')
        autor = data.get('autor')
        album = data.get('album')
        enlace = data.get('enlace')
        comentario = data.get('comentario_general')
        estado_cg = data.get('estado_cg_publicado')
        estado_cancion = data.get('estado_publicado')
        usuario_id = data.get('usuario_id')      # ← añade este campo en el JSON
        secciones = data.get("secciones", [])

        print(data)

        conn = get_db_connection()
        cur = conn.cursor()

        # ---------- INTENTAR UPDATE DE LA CANCIÓN ----------
        cur.execute("""
            UPDATE cancion
            SET nombre = %s,
                autor = %s,
                album = %s,
                enlace = %s,
                comentario_general = %s,
                estado_cg_publicado = %s,
                estado_publicado = %s,                    
                fecha_ultima_edicion = now()
            WHERE id = %s AND usuario_id = %s
        """, (nombre, autor, album, enlace, comentario, estado_cg, estado_cancion, song_id, usuario_id))

        # ---------- SI LA CANCIÓN NO EXISTE, INSERT ----------
        if cur.rowcount == 0:
            cur.execute("""
                INSERT INTO cancion (
                    usuario_id, nombre, autor, album, enlace, comentario_general,
                    estado_cg_publicado, estado_publicado,
                    fecha_creacion, fecha_ultima_edicion
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now(), now())
                RETURNING id, fecha_creacion, fecha_ultima_edicion
            """, (usuario_id, nombre, autor, album, enlace,
                  comentario, estado_cg, estado_cancion))
            row = cur.fetchone()
            new_song_id = row[0]

            # ─── NUEVO ▸ insertar TODAS las secciones recibidas ─────────────
            for sec in secciones:
                t_ini = sec.get("tiempo_inicio", "00:00:00")
                t_fin = sec.get("tiempo_final",  "00:00:00")
                nombre_sec = sec.get("nombre_seccion")
                comentario_sec = sec.get("comentario_seccion")
                publicado = sec.get("estado_cs_publicado", False)
                emociones = sec.get("emociones", [])
                generos = sec.get("generos", [])

                cur.execute("""
                    INSERT INTO seccion (
                        nombre, cancion_id, usuario_id,
                        tiempo_inicio, tiempo_final, comentario_seccion,
                        estado_cs_publicado
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (nombre_sec, new_song_id, usuario_id, t_ini, t_fin, comentario_sec,
                      publicado))
                sec_id = cur.fetchone()[0]
                sec["id"] = sec_id

                # EMOCIONES
                for emocion in emociones:
                    cur.execute("""
                        INSERT INTO emocion_seleccionada (seccion_id, palabra)
                        VALUES (%s, %s)
                    """, (sec_id, emocion))

                # GÉNEROS
                for genero_id in generos:
                    cur.execute("""
                        INSERT INTO seccion_genero (seccion_id, genero_id)
                        VALUES (%s, %s)
                    """, (sec_id, genero_id))
            # ────────────────────────────────────────────────────────────────

            conn.commit()
            return jsonify({
                "status":               "inserted_as_new",
                "id_real":              new_song_id,
                "fecha_creacion":       row[1].isoformat(),
                "fecha_ultima_edicion": row[2].isoformat(),
                "secciones":            secciones       # opcional
            }), 200
        
        else:
            # ---------- UPDATE EXISTENTE - SECCIONES TAMBIÉN ----------
            if secciones:
                # 1. Obtener IDs existentes
                cur.execute("""
                    SELECT id FROM seccion 
                    WHERE cancion_id = %s AND usuario_id = %s
                """, (song_id, usuario_id))
                ids_existentes = {r[0] for r in cur.fetchall()}

                nuevos_ids = {s.get("id", -1) for s in secciones}
                ids_a_eliminar = ids_existentes - nuevos_ids

                # 2. Eliminar secciones eliminadas y sus emociones/géneros
                for sec_id in ids_a_eliminar:
                    cur.execute("DELETE FROM emocion_seleccionada WHERE seccion_id = %s", (sec_id,))
                    cur.execute("DELETE FROM seccion_genero WHERE seccion_id = %s", (sec_id,))
                    cur.execute("DELETE FROM seccion WHERE id = %s", (sec_id,))

                # 3. Insertar o actualizar secciones nuevas
                for sec in secciones:
                    sec_id = sec.get("id", -1)
                    t_ini = sec.get("tiempo_inicio")
                    t_fin = sec.get("tiempo_final")
                    nombre_sec = sec.get("nombre_seccion")
                    comentario_sec = sec.get("comentario_seccion")
                    publicado = sec.get("estado_cs_publicado", False)
                    emociones = sec.get("emociones", [])
                    generos = sec.get("generos", [])

                    if sec_id in ids_existentes:
                        cur.execute("""
                            UPDATE seccion SET
                                tiempo_inicio = %s,
                                tiempo_final = %s,
                                nombre = %s,
                                comentario_seccion = %s,
                                estado_cs_publicado = %s,
                                fecha_ultima_edicion = now()
                            WHERE id = %s AND cancion_id = %s AND usuario_id = %s
                        """, (t_ini, t_fin, nombre_sec, comentario_sec, publicado, sec_id, song_id, usuario_id))

                        # Borrar emociones y géneros viejos
                        cur.execute("DELETE FROM emocion_seleccionada WHERE seccion_id = %s", (sec_id,))
                        cur.execute("DELETE FROM seccion_genero WHERE seccion_id = %s", (sec_id,))

                        # Insertar emociones nuevas
                        for emocion in emociones:
                            cur.execute("""
                                INSERT INTO emocion_seleccionada (seccion_id, palabra)
                                VALUES (%s, %s)
                            """, (sec_id, emocion))

                        # Insertar géneros nuevos
                        for genero_id in generos:
                            cur.execute("""
                                INSERT INTO seccion_genero (seccion_id, genero_id)
                                VALUES (%s, %s)
                            """, (sec_id, genero_id))
                    else:
                        cur.execute("""
                            INSERT INTO seccion (
                                nombre, cancion_id, usuario_id,
                                tiempo_inicio, tiempo_final, comentario_seccion,
                                estado_cs_publicado
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, (nombre_sec, song_id, usuario_id, t_ini, t_fin, comentario_sec, publicado))
                        sec_id = cur.fetchone()[0]
                        sec["id"] = sec_id

                        for emocion in emociones:
                            cur.execute("""
                                INSERT INTO emocion_seleccionada (seccion_id, palabra)
                                VALUES (%s, %s)
                            """, (sec_id, emocion))
                        for genero_id in generos:
                            cur.execute("""
                                INSERT INTO seccion_genero (seccion_id, genero_id)
                                VALUES (%s, %s)
                            """, (sec_id, genero_id))

            # 4. Obtener fecha actualizada desde base de datos (por trigger)
            cur.execute("""
                SELECT fecha_ultima_edicion
                FROM cancion
                WHERE id = %s
            """, (song_id,))
            result = cur.fetchone()
            fecha_ultima_edicion = result[0].isoformat() if result else None

            conn.commit()
            return jsonify({
                "status": "updated",
                "message": "Canción y secciones actualizadas",
                "fecha_ultima_edicion": fecha_ultima_edicion
            }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        if 'conn' in locals():
            conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        if 'cur' in locals(): cur.close()
        if 'conn' in locals(): conn.close()
    
@app.route('/api/actualizar_secciones', methods=['POST'])
def actualizar_secciones():
    data = request.get_json()
    cancion_id = data.get("cancion_id")
    usuario_id = data.get("usuario_id")
    nuevas_secciones = data.get("secciones", [])

    if not cancion_id or not usuario_id or not nuevas_secciones:
        return jsonify({"error": "Datos incompletos"}), 400

    try:
        # ✅ Conectar antes de cualquier cursor.execute()
        conn = get_db_connection()
        cursor = conn.cursor()

        # 0. Verificar existencia de la canción
        cursor.execute("SELECT 1 FROM cancion WHERE id = %s AND usuario_id = %s",
                    (cancion_id, usuario_id))
        if cursor.fetchone() is None:
            return jsonify({
                "status":  "song_not_found",
                "message": "La canción aún no existe en el servidor"
            }), 404

        # 1. Obtener las secciones existentes
        cursor.execute("""
            SELECT id FROM seccion 
            WHERE cancion_id = %s AND usuario_id = %s
        """, (cancion_id, usuario_id))
        secciones_existentes = cursor.fetchall()
        ids_existentes_en_bd = {s[0] for s in secciones_existentes}

        # 2. Calcular los IDs que deben eliminarse
        nuevos_ids_recibidos = {s.get("id", -1) for s in nuevas_secciones}
        ids_a_eliminar = ids_existentes_en_bd - nuevos_ids_recibidos

        # 3. Eliminar primero las secciones que ya no existen
        for sec_id in ids_a_eliminar:
            cursor.execute("""
                DELETE FROM seccion 
                WHERE id = %s AND cancion_id = %s AND usuario_id = %s
            """, (sec_id, cancion_id, usuario_id))

        # 4. Luego actualizar o insertar secciones
        for seccion in nuevas_secciones:
            sec_id = seccion.get("id", -1)
            tiempo_inicio = seccion.get("tiempo_inicio")
            tiempo_final = seccion.get("tiempo_final")

            if sec_id in ids_existentes_en_bd:
                cursor.execute("""
                    UPDATE seccion SET 
                        tiempo_inicio = %s,
                        tiempo_final = %s
                    WHERE id = %s AND cancion_id = %s AND usuario_id = %s
                """, (tiempo_inicio, tiempo_final, sec_id, cancion_id, usuario_id))
            else:
                cursor.execute("""
                    INSERT INTO seccion (cancion_id, usuario_id, tiempo_inicio, tiempo_final, estado_cs_publicado)
                    VALUES (%s, %s, %s, %s, false)
                """, (cancion_id, usuario_id, tiempo_inicio, tiempo_final))

        conn.commit()

        # 5. Obtener TODAS las secciones actualizadas con sus fechas y datos asociados
        cursor.execute("""
            SELECT 
                id, tiempo_inicio, tiempo_final, fecha_creacion, fecha_ultima_edicion,
                nombre, comentario_seccion, estado_cs_publicado
            FROM seccion
            WHERE cancion_id = %s AND usuario_id = %s
            ORDER BY tiempo_inicio
        """, (cancion_id, usuario_id))
        secciones_actualizadas = cursor.fetchall()

        resultado = [serialize_seccion(fila) for fila in secciones_actualizadas]

        return jsonify({
            "status": "ok",
            "mensaje": "Secciones sincronizadas correctamente",
            "new_ids": resultado
        }), 200

    except Exception as e:
        print("Error al actualizar secciones:", str(e))
        return jsonify({"error": "Error interno"}), 500

    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def serialize_seccion(seccion):
    seccion_id = seccion[0]

    # Obtener emociones
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT palabra FROM emocion_seleccionada WHERE seccion_id = %s
    """, (seccion_id,))
    emociones = [row[0] for row in cursor.fetchall()]

    # ✅ Obtener géneros con nombre
    cursor.execute("""
        SELECT g.id, g.nombre 
        FROM seccion_genero sg
        JOIN genero g ON sg.genero_id = g.id
        WHERE sg.seccion_id = %s
    """, (seccion_id,))
    generos = [{"id": row[0], "nombre_genero": row[1]} for row in cursor.fetchall()]

    cursor.close()

    return {
        'id': seccion[0],
        'tiempo_inicio': str(seccion[1]),
        'tiempo_final': str(seccion[2]),
        'fecha_creacion': seccion[3].strftime('%Y-%m-%d %H:%M:%S.%f') if seccion[3] else None,
        'fecha_ultima_edicion': seccion[4].strftime('%Y-%m-%d %H:%M:%S.%f') if seccion[4] else None,
        'nombre': seccion[5],
        'comentario': seccion[6],
        'estado_comentario': seccion[7],
        'emociones': emociones,
        'generos': generos  # ← Ya no son enteros planos
    }

#TODO
@app.route('/api/sincronizar_canciones', methods=['POST'])
def sincronizar_canciones():
    data = request.get_json()
    usuario_id = request.args.get("usuario_id", type=int)

    print("[SYNC]  request.content_type =", request.content_type)
    print("[SYNC]  request.content_length =", request.content_length)
    print("[SYNC]  raw first 500 bytes:", request.get_data()[:500])
    data = request.get_json(silent=True)   # silent evita abort 400 interno
    print("[SYNC]  parsed =", type(data), "len=", (len(data) if isinstance(data, list) else "n/a"))

    if not isinstance(data, list):
        return jsonify({"error": "Formato incorrecto, se esperaba una lista"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    canciones_insertadas = []

    try:
        # Obtener IDs y fechas actuales en la base de datos
        cur.execute("""
            SELECT id, fecha_ultima_edicion FROM cancion
            WHERE usuario_id = %s
        """, (usuario_id,))
        canciones_bd = {row['id']: row['fecha_ultima_edicion'] for row in cur.fetchall()}

        ids_recibidos = set()

        for cancion in data:
            id_temporal = cancion['id']
            fecha_local = datetime.fromisoformat(cancion['fechaUltimaEdicion'])
            ids_recibidos.add(id_temporal)

            # 1) Obtener el binario (o None)
            audio_bin = _decode_audio_b64(cancion.get('archivoBase64'))

            if id_temporal not in canciones_bd:
                # 🔹 Insertar canción SIN ID (para usar serial)
                cur.execute("""
                    INSERT INTO cancion (usuario_id, nombre, autor, album, enlace, comentario_general,
                        estado_cg_publicado, estado_publicado, fecha_creacion, fecha_ultima_edicion, archivo)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, fecha_creacion, fecha_ultima_edicion
                """, (
                    usuario_id, cancion['nombre'], cancion['autor'], cancion['album'],
                    cancion['enlaceRuta'],
                    cancion['comentario'], cancion['estadoComentario1'], cancion['publicado'],
                    cancion['fechaCreacion'], cancion['fechaUltimaEdicion'],
                    audio_bin
                ))
                row = cur.fetchone()
                nuevo_id_cancion = row['id']

                # Secciones insertadas
                secciones_insertadas = []
                for s in cancion.get('secciones', []):
                    cur.execute("""
                        INSERT INTO seccion (cancion_id, usuario_id, tiempo_inicio, tiempo_final,
                            fecha_creacion, fecha_ultima_edicion)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id, fecha_creacion, fecha_ultima_edicion
                    """, (
                        nuevo_id_cancion, usuario_id,
                        s['tiempoInicio'], s['tiempoFinal'],
                        s['fechaCreacion'], s['fechaUltimaEdicion']
                    ))
                    seccion_info = cur.fetchone()
                    secciones_insertadas.append({
                        "idTemporal": s['id'],  # ID temporal desde Android
                        "idReal": seccion_info['id'],
                        "fechaCreacion": seccion_info['fecha_creacion'].isoformat(),
                        "fechaUltimaEdicion": seccion_info['fecha_ultima_edicion'].isoformat()
                    })
                
                # Guardar en lista de cambios
                canciones_insertadas.append({
                    "idTemporal": id_temporal,
                    "idReal": nuevo_id_cancion,
                    "fechaCreacion": row['fecha_creacion'].isoformat(),
                    "fechaUltimaEdicion": row['fecha_ultima_edicion'].isoformat(),
                    "secciones": secciones_insertadas
                })

            else:
                fecha_bd = canciones_bd[id_temporal]
                if fecha_local > fecha_bd:
                    # 🔄 Actualizar canción existente
                    cur.execute("""
                        UPDATE cancion SET nombre = %s, autor = %s, album = %s, enlace = %s,
                            comentario_general = %s, estado_cg_publicado = %s, estado_publicado = %s,
                            fecha_creacion = %s, fecha_ultima_edicion = %s
                        WHERE id = %s AND usuario_id = %s
                    """, (
                        cancion['nombre'], cancion['autor'], cancion['album'], cancion['enlaceRuta'],
                        cancion['comentario'], cancion['estadoComentario1'], cancion['publicado'],
                        cancion['fechaCreacion'], cancion['fechaUltimaEdicion'],
                        id_temporal, usuario_id
                    ))

                    # 🔄 Reemplazar secciones
                    cur.execute("DELETE FROM seccion WHERE cancion_id = %s AND usuario_id = %s", (id_temporal, usuario_id))
                    for s in cancion.get('secciones', []):
                        cur.execute("""
                            INSERT INTO seccion (cancion_id, usuario_id, tiempo_inicio, tiempo_final,
                                fecha_creacion, fecha_ultima_edicion)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            id_temporal, usuario_id,
                            s['tiempoInicio'], s['tiempoFinal'],
                            s['fechaCreacion'], s['fechaUltimaEdicion']
                        ))

        # 🗑️ Eliminar canciones que ya no están localmente
        ids_bd = set(canciones_bd.keys())
        ids_a_eliminar = ids_bd - ids_recibidos
        for id_a_eliminar in ids_a_eliminar:
            cur.execute("DELETE FROM seccion WHERE cancion_id = %s AND usuario_id = %s", (id_a_eliminar, usuario_id))
            cur.execute("DELETE FROM cancion WHERE id = %s AND usuario_id = %s", (id_a_eliminar, usuario_id))

        conn.commit()
        return jsonify({
            "mensaje": "Sincronización completa",
            "cancionesNuevas": canciones_insertadas
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()        # <── añade esto
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()

def es_archivo_audio(nombre):
    return nombre.lower().endswith(('.mp3', '.wav', '.ogg'))

def _decode_audio_b64(b64str):
    try:
        return Binary(base64.b64decode(b64str)) if b64str else None
    except Exception:
        return None       # opcional: loggear error

if __name__ == "__main__":
    app.run(debug=True)
