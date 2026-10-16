from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, NoSuchWindowException, InvalidSessionIdException
import sys
import argparse
import time
import random
from datetime import datetime
import subprocess
import os
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import socket

try:
    import pyodbc
except ImportError:
    pyodbc = None

try:
    import openpyxl
except ImportError:
    openpyxl = None


def es_horario_laboral(dt=None):
    """
    Verifica si el momento actual (o el datetime provisto) está dentro del horario laboral.
    Horario laboral:
    - Lunes a Viernes (0-4): 07:00 a 17:00 (7am - 5pm)
    - Sábados (5): 07:00 a 14:00 (7am - 2pm)
    - Domingos (6): Sin atención
    """
    if dt is None:
        dt = datetime.now()
    dia = dt.weekday()
    hora = dt.hour
    if 0 <= dia <= 4:
        return 7 <= hora < 17
    elif dia == 5:
        return 7 <= hora < 14
    return False


class WhatsAppBotWeb:
    def __init__(self, bot_id=1, excel_path=None, force_excel=False):
        """
        bot_id: 1 o 2 — indica qué instancia de WhatsApp usar.
          Bot 1: Chrome puerto 9222, perfil ChromeWhatsApp1
          Bot 2: Chrome puerto 9223, perfil ChromeWhatsApp2
        excel_path: ruta al archivo de Excel para ambiente de pruebas.
        force_excel: fuertemente fuerza el uso de Excel en lugar de SQL Server.
        """
        self.bot_id = bot_id
        self.debug_port = 9221 + bot_id  # 9222 para bot 1, 9223 para bot 2
        self.user_data_dir = rf"C:\Temp\ChromeWhatsApp{bot_id}"
        self.excel_path = excel_path or "ambiente_pruebas.xlsx"
        self.force_excel = force_excel or os.path.exists(self.excel_path) or pyodbc is None
        print(f"INICIO DEL PROCESO — Bot {bot_id} (puerto {self.debug_port})")
        if self.force_excel:
            print(f"ℹ️ Bot {bot_id}: Operando en Ambiente de Pruebas con Excel: {self.excel_path}")
        self.driver = None
        self.ensure_chrome_running()

    # -------------------------------------------------------
    # Helpers de timing y texto
    # -------------------------------------------------------
    def _pausa_corta(self):
        """Pausa aleatoria corta (simula reacción humana)"""
        time.sleep(random.uniform(0.2, 0.7))

    def _pausa_media(self):
        """Pausa aleatoria media"""
        time.sleep(random.uniform(0.8, 1.8))

    def _pausa_larga(self):
        """Pausa aleatoria larga 3 - 6 segundos (entre mensajes)"""
        time.sleep(random.uniform(3.0, 6.0))

    def _escribir_lento(self, elemento, texto, min_delay=0.03, max_delay=0.10):
        """Escribe texto carácter a carácter con delays aleatorios"""
        for char in texto:
            elemento.send_keys(char)
            time.sleep(random.uniform(min_delay, max_delay))

    def _escribir_mensaje_normal(self, elemento, mensaje):
        """Escritura más natural para mensajes: rápida, con micro-pausas por puntuación."""
        for char in str(mensaje):
            if char == "\n":
                elemento.send_keys(Keys.SHIFT + Keys.ENTER)
                time.sleep(random.uniform(0.15, 0.35))
            elif char in [".", ",", ";", ":"]:
                elemento.send_keys(char)
                time.sleep(random.uniform(0.10, 0.25))
            else:
                elemento.send_keys(char)
                time.sleep(random.uniform(0.015, 0.05))

    def _normalizar_texto(self, texto):
        if texto is None:
            return ""
        return " ".join(str(texto).strip().lower().split())

    def _debug_log(self, mensaje):
        return

    def _esperar_chat_listo(self, timeout=4):
        inicio = time.time()
        while time.time() - inicio < timeout:
            try:
                self.driver.find_element(By.XPATH, "//div[@data-testid='conversation-compose-box-input']")
                return True
            except Exception:
                pass
            try:
                self.driver.find_element(By.XPATH, "//footer")
                return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def _debug_resultados_busqueda(self, termino, limite=8):
        try:
            filas = self.driver.find_elements(
                By.XPATH,
                "//div[@id='pane-side']//div[@role='row'][.//div[@data-testid='cell-frame-container']]"
            )
            self._debug_log(f"Resultados visibles para '{termino}': {len(filas)}")
            for idx, fila in enumerate(filas[:limite], start=1):
                texto = self._texto_resultado_visible(fila)
                self._debug_log(f"Resultado {idx}: {texto}")
        except Exception as e:
            self._debug_log(f"No se pudieron listar resultados para '{termino}': {e}")

    def _obtener_titulo_chat_abierto(self):
        xpaths_titulo = [
            "//header//span[@data-testid='conversation-info-header-chat-title']",
            "//header//div[@role='button']//span[@dir='auto']",
            "//header//span[@title]",
        ]
        for xpath in xpaths_titulo:
            try:
                elem = WebDriverWait(self.driver, 1.5).until(
                    EC.presence_of_element_located((By.XPATH, xpath))
                )
                titulo = (elem.get_attribute("title") or elem.text or "").strip()
                if titulo:
                    return titulo
            except Exception:
                continue
        return ""

    def _coincide_titulo(self, esperado, obtenido):
        esperado_norm = self._normalizar_texto(esperado)
        obtenido_norm = self._normalizar_texto(obtenido)
        if not esperado_norm or not obtenido_norm:
            return False
        return (
            esperado_norm == obtenido_norm
            or esperado_norm in obtenido_norm
            or obtenido_norm in esperado_norm
        )

    def _texto_resultado_visible(self, elemento):
        partes = []
        try:
            for atributo in ("title", "aria-label"):
                valor = elemento.get_attribute(atributo)
                if valor:
                    partes.append(valor)
        except Exception:
            pass

        try:
            if elemento.text:
                partes.append(elemento.text)
        except Exception:
            pass

        try:
            for subelem in elemento.find_elements(By.XPATH, ".//span[@title]"):
                valor = subelem.get_attribute("title") or subelem.text
                if valor:
                    partes.append(valor)
        except Exception:
            pass

        return self._normalizar_texto(" ".join(partes))

    def _seleccionar_resultado_visible(self, termino):
        termino_norm = self._normalizar_texto(termino)
        candidatos = self.driver.find_elements(
            By.XPATH,
            "//div[@id='pane-side']//div[@role='row'][.//div[@data-testid='cell-frame-container']]"
        )
        for candidato in candidatos:
            texto = self._texto_resultado_visible(candidato)
            if not texto:
                continue
            if texto == termino_norm or termino_norm in texto or texto in termino_norm:
                try:
                    contenedor = candidato.find_element(By.XPATH, ".//div[@data-testid='cell-frame-container']")
                    self.driver.execute_script("arguments[0].click();", contenedor)
                except Exception:
                    self.driver.execute_script("arguments[0].click();", candidato)
                return True
        return False

    def _abrir_grupo_por_nombre(self, nombre_grupo):
        objetivo = self._normalizar_texto(nombre_grupo)

        # 1) Coincidencia exacta por atributo title dentro del panel lateral
        try:
            spans = self.driver.find_elements(By.XPATH, "//div[@id='pane-side']//span[@title]")
            for sp in spans:
                titulo = self._normalizar_texto(sp.get_attribute("title") or sp.text)
                if titulo == objetivo:
                    try:
                        fila = sp.find_element(By.XPATH, "./ancestor::div[@role='row'][1]")
                        contenedor = fila.find_element(By.XPATH, ".//div[@data-testid='cell-frame-container']")
                        self.driver.execute_script("arguments[0].click();", contenedor)
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", sp)
                    return True
        except Exception:
            pass

        # 2) Respaldo: coincidencia por texto visible de la fila
        return self._seleccionar_resultado_visible(nombre_grupo)

    def _hay_resultado_grupo_visible(self, nombre_grupo):
        objetivo = self._normalizar_texto(nombre_grupo)

        try:
            spans = self.driver.find_elements(By.XPATH, "//div[@id='pane-side']//span[@title]")
            for sp in spans:
                titulo = self._normalizar_texto(sp.get_attribute("title") or sp.text)
                if titulo == objetivo:
                    return True
        except Exception:
            pass

        try:
            filas = self.driver.find_elements(
                By.XPATH,
                "//div[@id='pane-side']//div[@role='row'][.//div[@data-testid='cell-frame-container']]"
            )
            for fila in filas:
                texto = self._texto_resultado_visible(fila)
                if texto and objetivo in texto:
                    return True
        except Exception:
            pass

        return False

    def _abrir_primer_resultado_busqueda(self, caja_busqueda, termino):
        # Estrategia 1: navegación de teclado
        try:
            caja_busqueda.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.2)
            caja_busqueda.send_keys(Keys.ENTER)
            return True
        except Exception:
            pass

        # Estrategia 2: click al primer row/cell-frame disponible en side/pane-side
        xpaths_primer_resultado = [
            "(//div[@id='side']//div[@role='row'][.//div[@data-testid='cell-frame-container']]//div[@data-testid='cell-frame-container'])[1]",
            "(//div[@id='pane-side']//div[@role='row'][.//div[@data-testid='cell-frame-container']]//div[@data-testid='cell-frame-container'])[1]",
            "(//div[@id='side']//div[@role='row'])[1]",
            "(//div[@id='pane-side']//div[@role='row'])[1]",
        ]
        for xpath in xpaths_primer_resultado:
            try:
                elem = WebDriverWait(self.driver, 1.2).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                self.driver.execute_script("arguments[0].click();", elem)
                return True
            except Exception:
                continue

        return False

    # -------------------------------------------------------
    # Chrome y gestión de ventanas
    # -------------------------------------------------------
    def _puerto_en_uso(self, puerto):
        """Verifica si el puerto de depuración de Chrome ya está abierto"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex(('127.0.0.1', puerto)) == 0

    def _obtener_ruta_chrome(self):
        """Busca el ejecutable de Chrome en rutas estándar según el SO"""
        rutas_posibles = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        ]
        for ruta in rutas_posibles:
            if os.path.isfile(ruta):
                return ruta
        return "chrome"

    def ensure_chrome_running(self):
        """Asegura que Chrome esté ejecutándose en modo debug y conectado a WhatsApp"""
        user_data_dir = self.user_data_dir
        debug_port = self.debug_port

        if not os.path.exists(user_data_dir):
            try:
                os.makedirs(user_data_dir)
            except Exception as e:
                print(f"⚠️ No se pudo crear directorio {user_data_dir}: {e}")

        # Iniciar Chrome si el puerto no responde
        if not self._puerto_en_uso(debug_port):
            chrome_path = self._obtener_ruta_chrome()
            cmd = f'"{chrome_path}" --remote-debugging-port={debug_port} --user-data-dir="{user_data_dir}"'
            try:
                subprocess.Popen(cmd, shell=True)
                time.sleep(4)
            except Exception as e:
                print(f"❌ Error lanzando proceso de Chrome: {e}")

        # Intentar conectar con Selenium webdriver
        for intento in range(3):
            try:
                options = webdriver.ChromeOptions()
                options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
                self.driver = webdriver.Chrome(options=options)
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                self._ir_a_whatsapp()
                self._ensure_window_visible()
                print(f"✅ Chrome Bot {self.bot_id} conectado correctamente (puerto {debug_port})")
                return True
            except Exception as e:
                if intento < 2:
                    print(f"🔄 Reintentando conexión Bot {self.bot_id} ({intento + 1}/3)...")
                    time.sleep(3)
                else:
                    print(f"❌ Error al conectar Bot {self.bot_id}: {e}")
                    return False
        return False

    def _ir_a_whatsapp(self):
        """Navegar a WhatsApp Web y esperar que cargue la interfaz principal"""
        try:
            if "web.whatsapp.com" not in self.driver.current_url:
                self.driver.get("https://web.whatsapp.com")
                time.sleep(5)
            WebDriverWait(self.driver, 45).until(
                EC.presence_of_element_located((By.XPATH, "//div[@id='side']"))
            )
        except Exception:
            pass

    def _navegador_vivo(self):
        """Verifica si el navegador sigue activo y conectado."""
        if not self.driver:
            return False
        try:
            _ = self.driver.current_url
            return True
        except (WebDriverException, NoSuchWindowException, InvalidSessionIdException, AttributeError):
            return False

    def _reconectar(self):
        """Intenta reconectar a Chrome o abre una nueva instancia."""
        print(" Navegador cerrado detectado. Intentando reconectar...")
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self.driver = None
        if not self.ensure_chrome_running():
            raise Exception("No se pudo iniciar o reconectar Chrome")
        print(" Reconexión exitosa.")

    def _obtener_area_trabajo(self):
        """
        Obtiene el área de trabajo utilizable del monitor (descontando la barra de tareas de Windows).
        Retorna una tupla: (x, y, width, height)
        """
        try:
            if hasattr(ctypes, "windll"):
                user32 = ctypes.windll.user32
                rect = wintypes.RECT()
                # SPI_GETWORKAREA = 48 (0x0030)
                if user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                    x = rect.left
                    y = rect.top
                    ancho = rect.right - rect.left
                    alto = rect.bottom - rect.top
                    return x, y, ancho, alto

                # Fallback GetSystemMetrics
                pantalla_ancho = user32.GetSystemMetrics(0)
                pantalla_alto = user32.GetSystemMetrics(1)
                return 0, 0, pantalla_ancho, max(300, pantalla_alto - 40)
        except Exception as e:
            print(f"⚠️ Error obteniendo área de trabajo con ctypes: {e}")

        # Default fallback generico
        return 0, 0, 1920, 1040

    def _colocar_ventana_por_bot(self):
        """
        Ajusta la posición y tamaño de la ventana dividiendo la pantalla horizontalmente
        respetando el área de trabajo para que no quede por debajo de la barra de tareas.
        Bot 1: Mitad izquierda.
        Bot 2: Mitad derecha.
        """
        try:
            work_x, work_y, work_width, work_height = self._obtener_area_trabajo()
            mitad_ancho = max(400, work_width // 2)

            x_pos = work_x if self.bot_id == 1 else work_x + work_width - mitad_ancho

            self.driver.set_window_rect(
                x=x_pos,
                y=work_y,
                width=mitad_ancho,
                height=work_height
            )
            time.sleep(0.3)
        except Exception as e:
            print(f"⚠️ No se pudo acomodar ventana de Bot {self.bot_id}: {e}")

    def _ensure_window_visible(self):
        """Asegura que la ventana activa del bot sea visible y esté en su mitad de pantalla."""
        try:
            self.driver.switch_to.window(self.driver.current_window_handle)
            self._colocar_ventana_por_bot()
        except Exception as e:
            print(f"⚠️ No se pudo verificar/ajustar visibilidad: {e}")

    # -------------------------------------------------------
    # Acceso a Datos (SQL Server & Excel)
    # -------------------------------------------------------
    def cnx_empresas(self):
        if self.force_excel or pyodbc is None:
            return None
        try:
            pwd = "PRUEBAS"
            conexion_str = (
                'DRIVER={ODBC Driver 17 for SQL Server};'
                'SERVER=192.168.1.1;DATABASE=DBPRUEBAS;'
                f'UID=PRUEBAS;PWD={pwd}'
            )
            return pyodbc.connect(conexion_str, timeout=3)
        except Exception as e:
            print("⚠️ No se pudo conectar a SQL Server. Usando ambiente de Excel:", e)
            self.force_excel = True
            return None

    def actualizar_mensaje(self, id_registro, estatus, error=None):
        if self.force_excel or not os.path.exists(self.excel_path):
            return self._actualizar_mensaje_excel(id_registro, estatus, error)

        conn = self.cnx_empresas()
        if not conn:
            return self._actualizar_mensaje_excel(id_registro, estatus, error)

        try:
            cursor = conn.cursor()
            if estatus == 'E':
                cursor.execute(
                    "UPDATE Clt_BitacoraWhatsappBot SET estatus=?, fecha_envio=? WHERE id=?",
                    (estatus, datetime.now(), id_registro)
                )
            elif estatus == 'F':
                cursor.execute(
                    "UPDATE Clt_BitacoraWhatsappBot SET estatus=?, error=? WHERE id=?",
                    (estatus, str(error)[:500] if error else "", id_registro)
                )
            else:
                cursor.execute(
                    "UPDATE Clt_BitacoraWhatsappBot SET estatus=? WHERE id=?",
                    (estatus, id_registro)
                )
            conn.commit()
            if error:
                print(f"  Error registrado: {str(error)[:100]}")
            return True
        except Exception as e:
            print(f"Error actualizando BD: {e}")
            return self._actualizar_mensaje_excel(id_registro, estatus, error)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _actualizar_mensaje_excel(self, id_registro, estatus, error=None):
        if openpyxl is None:
            print("❌ openpyxl no está instalado. No se puede actualizar el archivo Excel.")
            return False

        if not os.path.exists(self.excel_path):
            print(f"❌ Archivo Excel {self.excel_path} no existe.")
            return False

        try:
            wb = openpyxl.load_workbook(self.excel_path)
            ws = wb.active

            headers = [str(cell.value).strip().lower() if cell.value else "" for cell in ws[1]]
            col_idx = {name: idx + 1 for idx, name in enumerate(headers)}

            id_col = col_idx.get("id")
            estatus_col = col_idx.get("estatus")
            fecha_envio_col = col_idx.get("fecha_envio")
            error_col = col_idx.get("error")

            if not id_col or not estatus_col:
                print("❌ El archivo Excel no contiene las columnas requeridas (id, estatus).")
                return False

            for row in range(2, ws.max_row + 1):
                cell_id = ws.cell(row=row, column=id_col).value
                if cell_id is not None and str(cell_id).strip() == str(id_registro).strip():
                    ws.cell(row=row, column=estatus_col, value=estatus)
                    if estatus == 'E' and fecha_envio_col:
                        ws.cell(row=row, column=fecha_envio_col, value=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    elif estatus == 'F' and error_col:
                        ws.cell(row=row, column=error_col, value=str(error)[:500] if error else "")
                    wb.save(self.excel_path)
                    if error:
                        print(f"  Error registrado en Excel: {str(error)[:100]}")
                    return True

            print(f"⚠️ Registro id={id_registro} no encontrado en Excel.")
            return False
        except Exception as e:
            print(f"❌ Error actualizando Excel: {e}")
            return False

    def obtener_mensajes_pendientes_excel(self):
        if openpyxl is None or not os.path.exists(self.excel_path):
            return []

        try:
            wb = openpyxl.load_workbook(self.excel_path, data_only=True)
            ws = wb.active

            headers = [str(cell.value).strip().lower() if cell.value else "" for cell in ws[1]]
            col_idx = {name: idx + 1 for idx, name in enumerate(headers)}

            id_col = col_idx.get("id")
            num_col = col_idx.get("numero")
            msg_col = col_idx.get("mensaje")
            pan_col = col_idx.get("pantalla")
            est_col = col_idx.get("estatus")
            bot_col = col_idx.get("numero_bot")

            mensajes = []
            paridad_bot = self.bot_id % 2

            for row in range(2, ws.max_row + 1):
                estatus = str(ws.cell(row=row, column=est_col).value or "").strip().upper()
                if estatus not in ('P', 'F'):
                    continue

                id_msg = ws.cell(row=row, column=id_col).value
                if id_msg is None:
                    continue

                num_bot_val = ws.cell(row=row, column=bot_col).value if bot_col else None
                try:
                    num_bot = int(num_bot_val) if num_bot_val is not None and str(num_bot_val).strip().isdigit() else None
                except Exception:
                    num_bot = None

                # Reglas de asignacion
                corresponde = False
                if num_bot is not None and num_bot in (1, 2):
                    if num_bot == self.bot_id:
                        corresponde = True
                else:
                    try:
                        if (int(id_msg) % 2) == paridad_bot:
                            corresponde = True
                    except Exception:
                        corresponde = True

                if corresponde:
                    numero = str(ws.cell(row=row, column=num_col).value or "").strip()
                    mensaje = str(ws.cell(row=row, column=msg_col).value or "").strip()
                    pantalla = str(ws.cell(row=row, column=pan_col).value or "").strip() if pan_col else ""
                    mensajes.append((id_msg, numero, mensaje, pantalla))

            return mensajes
        except Exception as e:
            print(f"❌ Error leyendo mensajes de Excel: {e}")
            return []

    # -------------------------------------------------------
    # Envío de Mensajes
    # -------------------------------------------------------
    def _buscar_contacto(self, numero):
        """
        Busca el número o nombre de grupo en la barra de búsqueda de WhatsApp Web.
        Abre el chat correspondiente. Si no lo encuentra, lanza Excepción sin enviar
        mensajes a chats incorrectos.
        """
        destino_texto = str(numero).strip()
        numero_limpio = destino_texto.replace("+", "").replace(" ", "").replace("-", "")
        es_numero = numero_limpio.isdigit()

        xpaths_busqueda = [
            "//input[@role='textbox'][@data-tab='3']",
            "//input[@placeholder='Buscar un chat o iniciar uno nuevo']",
            "//input[contains(@aria-label,'Buscar un chat o iniciar uno nuevo')]",
            "//input[contains(@aria-label,'Search or start new chat')]",
            "//div[@contenteditable='true'][@data-tab='3']",
            "//div[@data-testid='chat-list-search']",
            "//div[@aria-label='Buscar o iniciar un nuevo chat']",
            "//div[@aria-label='Search or start new chat']",
            "//div[@aria-label='Search input textbox']",
            "//div[@aria-label='Cuadro de texto de búsqueda']",
            "//div[@title='Search input textbox']",
            "//div[@id='side']//div[@contenteditable='true']",
        ]

        caja_busqueda = None
        for xpath in xpaths_busqueda:
            try:
                caja_busqueda = WebDriverWait(self.driver, 4).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                break
            except Exception:
                continue

        if not caja_busqueda:
            raise Exception("No se encontró la barra de búsqueda en WhatsApp Web")

        # Construir variantes de búsqueda
        if es_numero:
            if numero_limpio.startswith("521") and len(numero_limpio) > 11:
                variantes = [numero_limpio, "52" + numero_limpio[3:], numero_limpio[3:]]
            elif numero_limpio.startswith("52") and len(numero_limpio) > 10:
                variantes = [numero_limpio, "521" + numero_limpio[2:], numero_limpio[2:]]
            else:
                variantes = [numero_limpio]
            if len(numero_limpio) > 10:
                variantes.append(numero_limpio[-10:])
        else:
            variantes = [destino_texto]

        variantes_unicas = list(dict.fromkeys(v for v in variantes if v))

        self.driver.execute_script("arguments[0].click();", caja_busqueda)
        self._pausa_corta()

        chat_abierto = False

        for termino in variantes_unicas:
            caja_busqueda.send_keys(Keys.CONTROL + "a")
            caja_busqueda.send_keys(Keys.DELETE)
            self._escribir_lento(caja_busqueda, termino, 0.015, 0.04)
            self._pausa_corta()

            if not es_numero:
                # Flujo para grupos / nombres de chat
                if self._hay_resultado_grupo_visible(termino):
                    try:
                        caja_busqueda.send_keys(Keys.ENTER)
                        if self._esperar_chat_listo(timeout=6):
                            titulo_abierto = self._obtener_titulo_chat_abierto()
                            if self._coincide_titulo(destino_texto, titulo_abierto) or titulo_abierto:
                                chat_abierto = True
                                print(f"  Grupo/Chat abierto con ENTER: {termino}")
                                break
                    except Exception:
                        pass

                if not chat_abierto and self._abrir_grupo_por_nombre(termino):
                    if self._esperar_chat_listo(timeout=6):
                        titulo_abierto = self._obtener_titulo_chat_abierto()
                        if self._coincide_titulo(destino_texto, titulo_abierto) or titulo_abierto:
                            chat_abierto = True
                            print(f"  Grupo/Chat localizado por clic: {termino}")
                            break

                if not chat_abierto and self._abrir_primer_resultado_busqueda(caja_busqueda, termino):
                    if self._esperar_chat_listo(timeout=6):
                        titulo_abierto = self._obtener_titulo_chat_abierto()
                        if self._coincide_titulo(destino_texto, titulo_abierto) or titulo_abierto:
                            chat_abierto = True
                            print(f"  Grupo/Chat abierto por primer resultado: {termino}")
                            break

                continue

            # Flujo para números individuales
            no_resultado = False
            try:
                WebDriverWait(self.driver, 1.5).until(
                    EC.presence_of_element_located((By.XPATH,
                        "//*[@data-testid='search-no-chats-or-contacts'] | "
                        "//span[contains(text(),'No se encontró ningún chat')]"
                    ))
                )
                no_resultado = True
                print(f"  Sin resultados para número: {termino}")
            except Exception:
                pass

            if no_resultado:
                continue

            # Intentar clic en resultado
            xpaths_resultado = [
                f"//div[@id='pane-side']//span[@title='{termino}']/ancestor::div[@data-testid='cell-frame-container'][1]",
                f"//div[@id='pane-side']//span[contains(@title,'{termino}')]/ancestor::div[@data-testid='cell-frame-container'][1]",
                f"//div[@id='pane-side']//span[@title='{termino}']/ancestor::div[@role='listitem'][1]",
                f"//div[@id='pane-side']//span[contains(@title,'{termino}')]/ancestor::div[@role='listitem'][1]",
                f"//div[@id='pane-side']//div[@data-testid='cell-frame-container'][.//span[contains(text(),'{termino[-8:]}')]]",
                f"//div[@id='pane-side']//div[@role='listitem'][.//span[contains(text(),'{termino[-8:]}')]]",
            ]

            for xpath in xpaths_resultado:
                try:
                    primer_resultado = WebDriverWait(self.driver, 0.8).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    self.driver.execute_script("arguments[0].click();", primer_resultado)
                    if self._esperar_chat_listo(timeout=5):
                        chat_abierto = True
                        print(f"  Contacto localizado con clic: {termino}")
                        break
                except Exception:
                    continue

            if not chat_abierto:
                # Clic en primer elemento de la lista de busqueda
                if self._abrir_primer_resultado_busqueda(caja_busqueda, termino):
                    if self._esperar_chat_listo(timeout=5):
                        chat_abierto = True
                        print(f"  Contacto abierto con primer resultado de lista: {termino}")
                        break

            if not chat_abierto:
                try:
                    caja_busqueda.send_keys(Keys.ENTER)
                    if self._esperar_chat_listo(timeout=5):
                        chat_abierto = True
                        print(f"  Contacto abierto con ENTER usando: {termino}")
                        break
                except Exception:
                    pass

            if chat_abierto:
                break

        if not chat_abierto:
            # Limpiar caja de busqueda para evitar dejar texto colgado
            try:
                caja_busqueda.send_keys(Keys.ESCAPE)
            except Exception:
                pass
            raise Exception(f"No se encontró el contacto o grupo '{destino_texto}' en WhatsApp Web")

        return True

    def _pegar_mensaje(self, mensaje, rapido=False):
        """
        Busca la caja de texto del chat abierto, escribe el mensaje y lo envía.
        """
        xpaths_input = [
            "//div[@data-testid='conversation-compose-box-input']",
            "//footer//div[@contenteditable='true'][@role='textbox']",
            "//div[@aria-label='Escribe un mensaje aquí']",
            "//div[@aria-label='Type a message']",
            "//footer//div[@data-lexical-editor='true']",
            "//footer//div[@contenteditable='true']",
        ]

        caja_texto = None
        for xpath in xpaths_input:
            try:
                caja_texto = WebDriverWait(self.driver, 1.5 if rapido else 3.0).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                break
            except Exception:
                continue

        if not caja_texto:
            raise Exception("No se encontró la caja de texto para redactar el mensaje")

        try:
            self.driver.execute_script("arguments[0].click(); arguments[0].focus();", caja_texto)
            time.sleep(0.1)
            self._escribir_mensaje_normal(caja_texto, mensaje)
            time.sleep(0.1)
        except Exception as e:
            try:
                caja_texto.send_keys(str(mensaje))
                time.sleep(0.2)
            except Exception as e2:
                raise Exception(f"No se pudo escribir el mensaje: {e2}")

        # Intentar clic en el botón Enviar
        xpaths_enviar = [
            "//button[@data-testid='send']",
            "//button[@aria-label='Enviar']",
            "//button[@aria-label='Send']",
            "//span[@data-icon='send']/ancestor::button[1]"
        ]

        for xpath in xpaths_enviar:
            try:
                btn_enviar = WebDriverWait(self.driver, 2.5).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                self.driver.execute_script("arguments[0].click();", btn_enviar)
                return True
            except Exception:
                continue

        # Fallback: Enter
        try:
            caja_texto.send_keys(Keys.ENTER)
            return True
        except Exception as e:
            raise Exception(f"Falló el envío de mensaje por botón o ENTER: {e}")

    def enviar(self, id_registro, numero, mensaje, pantalla):
        """Flujo: marcar como Procesando → buscar contacto → escribir mensaje → enviar"""
        self.actualizar_mensaje(id_registro, 'P')

        for intento in range(2):
            try:
                if not self._navegador_vivo():
                    self._reconectar()

                self._ensure_window_visible()
                self._ir_a_whatsapp()

                self._buscar_contacto(numero)
                numero_limpio = str(numero).replace("+", "").replace(" ", "").replace("-", "")
                es_numero = numero_limpio.isdigit()
                self._pegar_mensaje(mensaje, rapido=es_numero)

                time.sleep(1)
                self.actualizar_mensaje(id_registro, 'E')
                print(f"✅ Mensaje enviado exitosamente a: {numero}")
                return True

            except (WebDriverException, NoSuchWindowException, InvalidSessionIdException) as e:
                if intento == 0:
                    print("⚠️ Navegador caído durante el envío. Intentando reconectar...")
                    try:
                        self._reconectar()
                    except Exception as re:
                        error_msg = f"No se pudo reconectar el navegador: {re}"
                        print(f"❌ {error_msg}")
                        self.actualizar_mensaje(id_registro, 'F', error_msg)
                        return False
                else:
                    error_msg = str(e)
                    print(f"❌ Error al enviar a {numero} tras reconexión: {error_msg}")
                    self.actualizar_mensaje(id_registro, 'F', error_msg)
                    return False

            except Exception as e:
                error_msg = str(e)
                print(f"❌ Error al enviar a {numero}: {error_msg}")
                self.actualizar_mensaje(id_registro, 'F', error_msg)
                return False

        return False

    # -------------------------------------------------------
    # Loop principal
    # -------------------------------------------------------
    def enviar_mensajes_pendientes(self):
        mensajes = []

        if self.force_excel:
            mensajes = self.obtener_mensajes_pendientes_excel()
        else:
            conn = self.cnx_empresas()
            if conn:
                try:
                    cursor = conn.cursor()
                    paridad_bot = self.bot_id % 2
                    cursor.execute("""
                        SELECT id, numero, mensaje, pantalla
                        FROM Clt_BitacoraWhatsappBot
                        WHERE estatus IN ('P','F')
                          AND (
                                numero_bot = ?
                                OR ((numero_bot IS NULL OR numero_bot = 0) AND (id % 2) = ?)
                          )
                        ORDER BY fecha_registro ASC
                    """, (self.bot_id, paridad_bot))
                    mensajes = cursor.fetchall()
                    conn.close()
                except Exception as e:
                    print(f"⚠️ Error obteniendo mensajes de SQL Server: {e}")
                    mensajes = self.obtener_mensajes_pendientes_excel()
            else:
                mensajes = self.obtener_mensajes_pendientes_excel()

        if not mensajes:
            hora_py = datetime.now().strftime("%H:%M:%S")
            print(f"NO HAY MENSAJES PENDIENTES - Bot {self.bot_id} - Hora: {hora_py}")
            return

        print(f"\n--- Bot {self.bot_id}: procesando {len(mensajes)} mensajes pendientes ---")

        for msg in mensajes:
            id_msg, numero, mensaje, pantalla = msg
            self.enviar(id_msg, numero, mensaje, pantalla)
            self._pausa_larga()

    def cerrar(self):
        if self.driver:
            try:
                self.driver.quit()
                print(f" Bot {self.bot_id}: Navegador cerrado")
            except Exception:
                pass


# ========== EJECUCIÓN PRINCIPAL ==========
if __name__ == "__main__":
    bots = []

    try:
        parser = argparse.ArgumentParser(description='WhatsApp Bot Web')
        parser.add_argument('--modo-pendientes', action='store_true',
                            help='Ejecutar solo una vez el envío de mensajes pendientes')
        parser.add_argument('--modo-normal', action='store_true',
                            help='Ejecutar modo normal con loop (default)')
        parser.add_argument('--bot-id', type=int, choices=[1, 2],
                            help='ID del bot: 1 (puerto 9222) o 2 (puerto 9223). Si no se indica, inicia ambos bots')
        parser.add_argument('--excel', action='store_true',
                            help='Usar ambiente de pruebas con archivo Excel')
        parser.add_argument('--excel-file', type=str, default='ambiente_pruebas.xlsx',
                            help='Ruta al archivo de Excel para ambiente de pruebas')
        args = parser.parse_args()

        bot_ids = [args.bot_id] if args.bot_id else [1, 2]
        for b_id in bot_ids:
            bot = WhatsAppBotWeb(
                bot_id=b_id,
                excel_path=args.excel_file,
                force_excel=args.excel
            )
            bots.append(bot)

        if args.modo_pendientes:
            try:
                with ThreadPoolExecutor(max_workers=len(bots)) as executor:
                    futures = [executor.submit(bot.enviar_mensajes_pendientes) for bot in bots]
                    for future in futures:
                        future.result()
            except Exception as e:
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                for bot in bots:
                    bot.cerrar()
        else:
            def ejecutar_envio_si_horario():
                if es_horario_laboral():
                    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Ejecutando envío programado...")
                    with ThreadPoolExecutor(max_workers=len(bots)) as executor:
                        futures = [executor.submit(bot.enviar_mensajes_pendientes) for bot in bots]
                        for future in futures:
                            future.result()
                else:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fuera de horario laboral (L-V 7am-5pm, Sáb 7am-2pm).")

            print("Sistema iniciado. Horario laboral: Lunes a Viernes 7:00-17:00, Sábados 7:00-14:00")
            print("Ejecutando revisión de mensajes...")
            print("=" * 50)

            while True:
                ejecutar_envio_si_horario()
                time.sleep(60)

    except KeyboardInterrupt:
        print("\n PROCESO INTERRUMPIDO POR EL USUARIO")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if bots:
            print("\n FIN DEL PROCESO")
            for bot in bots:
                bot.cerrar()
