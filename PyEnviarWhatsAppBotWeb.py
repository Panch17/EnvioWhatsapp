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
import pyodbc
from datetime import datetime
import subprocess
import os
from concurrent.futures import ThreadPoolExecutor
import ctypes

class WhatsAppBotWeb:
    def __init__(self, bot_id=1):
        """
        bot_id: 1 o 2 — indica qué instancia de WhatsApp usar.
          Bot 1: Chrome puerto 9222, perfil ChromeWhatsApp1
          Bot 2: Chrome puerto 9223, perfil ChromeWhatsApp2
        """
        self.bot_id = bot_id
        self.debug_port = 9221 + bot_id          # 9222 para bot 1, 9223 para bot 2
        self.user_data_dir = rf"C:\Temp\ChromeWhatsApp{bot_id}"
        print(f"INICIO DEL PROCESO — Bot {bot_id} (puerto {self.debug_port})")
        self.driver = None
        self.ensure_chrome_running()

    # -------------------------------------------------------
    # Helpers de timing
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
        for char in mensaje:
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
            except:
                pass
            try:
                self.driver.find_element(By.XPATH, "//footer")
                return True
            except:
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
            except:
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
        except:
            pass

        try:
            if elemento.text:
                partes.append(elemento.text)
        except:
            pass

        try:
            for subelem in elemento.find_elements(By.XPATH, ".//span[@title]"):
                valor = subelem.get_attribute("title") or subelem.text
                if valor:
                    partes.append(valor)
        except:
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
                except:
                    self.driver.execute_script("arguments[0].click();", candidato)
                return True
        return False

    def _abrir_grupo_por_nombre(self, nombre_grupo):
        objetivo = self._normalizar_texto(nombre_grupo)

        # 1) Prioridad: coincidencia exacta por atributo title dentro del panel lateral.
        try:
            spans = self.driver.find_elements(By.XPATH, "//div[@id='pane-side']//span[@title]")
            self._debug_log(f"Spans con title detectados: {len(spans)} para '{nombre_grupo}'")
            for sp in spans:
                titulo = self._normalizar_texto(sp.get_attribute("title") or sp.text)
                if titulo == objetivo:
                    try:
                        fila = sp.find_element(By.XPATH, "./ancestor::div[@role='row'][1]")
                        contenedor = fila.find_element(By.XPATH, ".//div[@data-testid='cell-frame-container']")
                        self.driver.execute_script("arguments[0].click();", contenedor)
                    except:
                        self.driver.execute_script("arguments[0].click();", sp)
                    self._debug_log(f"Coincidencia exacta encontrada y clic en '{nombre_grupo}'")
                    return True
        except:
            pass

        # 2) Respaldo: coincidencia por texto visible de la fila.
        seleccionado = self._seleccionar_resultado_visible(nombre_grupo)
        self._debug_log(
            f"Coincidencia por texto visible para '{nombre_grupo}': {'SI' if seleccionado else 'NO'}"
        )
        return seleccionado

    def _hay_resultado_grupo_visible(self, nombre_grupo):
        objetivo = self._normalizar_texto(nombre_grupo)

        try:
            spans = self.driver.find_elements(By.XPATH, "//div[@id='pane-side']//span[@title]")
            for sp in spans:
                titulo = self._normalizar_texto(sp.get_attribute("title") or sp.text)
                if titulo == objetivo:
                    self._debug_log(f"Resultado exacto visible por title para '{nombre_grupo}'")
                    return True
        except Exception as e:
            self._debug_log(f"Error revisando spans title para '{nombre_grupo}': {e}")

        try:
            filas = self.driver.find_elements(
                By.XPATH,
                "//div[@id='pane-side']//div[@role='row'][.//div[@data-testid='cell-frame-container']]"
            )
            for fila in filas:
                texto = self._texto_resultado_visible(fila)
                if texto and objetivo in texto:
                    self._debug_log(f"Resultado visible por texto para '{nombre_grupo}'")
                    return True
        except Exception as e:
            self._debug_log(f"Error revisando filas visibles para '{nombre_grupo}': {e}")

        return False

    def _abrir_primer_resultado_busqueda(self, caja_busqueda, termino):
        # Estrategia 1: navegación de teclado (robusta ante cambios de DOM)
        try:
            caja_busqueda.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.2)
            caja_busqueda.send_keys(Keys.ENTER)
            self._debug_log(f"Primer resultado abierto con ARROW_DOWN+ENTER para '{termino}'")
            return True
        except Exception as e:
            self._debug_log(f"Falló ARROW_DOWN+ENTER para '{termino}': {e}")

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
                self._debug_log(f"Primer resultado abierto con click xpath: {xpath}")
                return True
            except Exception:
                continue

        self._debug_log(f"No se pudo abrir primer resultado para '{termino}'")
        return False

    # -------------------------------------------------------
    # Chrome
    # -------------------------------------------------------
    def ensure_chrome_running(self):
        """Asegura que Chrome esté ejecutándose en modo debug y conectado a WhatsApp"""
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        user_data_dir = self.user_data_dir
        debug_port   = self.debug_port
        
        # Crear directorio de perfil si no existe
        if not os.path.exists(user_data_dir):
            os.makedirs(user_data_dir)
        
        # Iniciar Chrome en modo debug con el puerto y perfil de este bot
        cmd = f'"{chrome_path}" --remote-debugging-port={debug_port} --user-data-dir="{user_data_dir}"'
        subprocess.Popen(cmd, shell=True)
        time.sleep(6)  # Esperar a que Chrome se inicie completamente
        
        # Intentar conectar con reintentos
        for intento in range(3):
            try:
                options = webdriver.ChromeOptions()
                options.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")
                self.driver = webdriver.Chrome(options=options)
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                self.driver.maximize_window()
                self._ir_a_whatsapp()
                self._ensure_window_visible()
                print(f"✅ Chrome Bot {self.bot_id} conectado correctamente (puerto {debug_port})")
                return True
            except Exception as e:
                if intento < 2:
                    print(f"🔄 Reintentando conexión Bot {self.bot_id} ({intento + 1}/3)...")
                    time.sleep(5)
                else:
                    print(f"❌ Error al conectar Bot {self.bot_id}: {e}")
                    return False
        return False

    def _ir_a_whatsapp(self):
        """Navegar a WhatsApp Web y esperar que cargue la interfaz principal"""
        if "web.whatsapp.com" not in self.driver.current_url:
            self.driver.get("https://web.whatsapp.com")
            time.sleep(8)
        # Esperar que aparezca el panel lateral (indica que está logueado y cargado)
        try:
            WebDriverWait(self.driver, 60).until(
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
        except:
            pass
        self.driver = None
        if not self.ensure_chrome_running():
            raise Exception("No se pudo iniciar o reconectar Chrome")
        print(" Reconexión exitosa.")

    def _ensure_window_visible(self):
        """Asegura que la ventana activa del bot sea visible y esté en su mitad de pantalla."""
        try:
            self.driver.switch_to.window(self.driver.current_window_handle)
            self._colocar_ventana_por_bot()
        except Exception as e:
            print(f" No se pudo verificar/ajustar visibilidad: {e}")

    def _colocar_ventana_por_bot(self):
        """Coloca Bot 1 en la mitad izquierda y Bot 2 en la mitad derecha."""
        try:
            user32 = ctypes.windll.user32
            pantalla_ancho = user32.GetSystemMetrics(0)
            pantalla_alto = user32.GetSystemMetrics(1)
            mitad_ancho = max(400, pantalla_ancho // 2)

            x_pos = 0 if self.bot_id == 1 else pantalla_ancho - mitad_ancho

            self.driver.set_window_rect(
                x=x_pos,
                y=0,
                width=mitad_ancho,
                height=pantalla_alto
            )
            time.sleep(0.5)
        except Exception as e:
            print(f" No se pudo acomodar ventana de Bot {self.bot_id}: {e}")

    # -------------------------------------------------------
    # Base de datos
    # -------------------------------------------------------
    def cnx_empresas(self):
        try:
            pwd = "PRUEBAS"
            conexion_str = (
                'DRIVER={ODBC Driver 17 for SQL Server};'
                'SERVER=192.168.1.1;DATABASE=DBPRUEBAS;'
                f'UID=PRUEBAS;PWD={pwd}'
            )
            return pyodbc.connect(conexion_str)
        except pyodbc.Error as e:
            print("Error al conectar a SQL Server:", e)
            return None

    def actualizar_mensaje(self, id_registro, estatus, error=None):
        conn = self.cnx_empresas()
        if not conn:
            return False
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
                    (estatus, error[:500], id_registro)
                )
            else:
                cursor.execute(
                    "UPDATE Clt_BitacoraWhatsappBot SET estatus=? WHERE id=?",
                    (estatus, id_registro)
                )
            conn.commit()
            if error:
                print(f"  Error registrado: {error[:100]}")
            return True
        except Exception as e:
            print(f"Error actualizando BD: {e}")
            return False
        finally:
            conn.close()

    # -------------------------------------------------------
    # Envío
    # -------------------------------------------------------
    def _buscar_contacto(self, numero):
        """
        Busca el número o nombre de grupo en la barra de búsqueda de WhatsApp Web.
        Retorna True si el chat fue abierto, False si no se encontró.
        """
        destino_texto = str(numero).strip()
        numero_limpio = destino_texto.replace("+", "").replace(" ", "").replace("-", "")
        es_numero = numero_limpio.isdigit()

        # Selectores para la caja de búsqueda — WhatsApp cambia entre input y div editable
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
                caja_busqueda = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                print(f"  Buscador encontrado con: {xpath}")
                break
            except:
                continue

        if not caja_busqueda:
            # Debug: mostrar posibles inputs/divs de búsqueda para diagnosticar cambios de UI
            try:
                inputs = self.driver.find_elements(By.XPATH, "//input[@role='textbox']")
                info_inputs = [
                    (
                        i.get_attribute('data-tab'),
                        i.get_attribute('aria-label'),
                        i.get_attribute('placeholder')
                    )
                    for i in inputs[:5]
                ]
                print(f"  inputs textbox encontrados: {info_inputs}")
                divs = self.driver.find_elements(By.XPATH, "//div[@contenteditable='true']")
                info = [(d.get_attribute('data-tab'), d.get_attribute('aria-label'), d.get_attribute('class')[:40] if d.get_attribute('class') else '') for d in divs[:5]]
                print(f"  divs contenteditable encontrados: {info}")
            except:
                pass
            raise Exception("No se encontró la barra de búsqueda de WhatsApp Web")

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
            # Nombre de grupo o contacto — buscar tal cual
            variantes = [destino_texto]

        # Eliminar duplicados manteniendo orden
        variantes_unicas = list(dict.fromkeys(v for v in variantes if v))

        self.driver.execute_script("arguments[0].click();", caja_busqueda)
        self._pausa_corta()

        chat_abierto = False

        for termino in variantes_unicas:
            # Limpiar y escribir el término
            caja_busqueda.send_keys(Keys.CONTROL + "a")
            caja_busqueda.send_keys(Keys.DELETE)
            self._escribir_lento(caja_busqueda, termino, 0.015, 0.04)
            self._pausa_corta()

            if not es_numero:
                # Para grupos: primero intentar ENTER si el resultado exacto está visible.
                abierto_por_enter = False
                if self._hay_resultado_grupo_visible(termino):
                    try:
                        caja_busqueda.send_keys(Keys.ENTER)
                        if self._esperar_chat_listo(timeout=8):
                            chat_abierto = True
                            abierto_por_enter = True
                            print(f"  Grupo abierto con ENTER usando: {termino}")
                            self._debug_log(f"Chat listo para grupo '{termino}' con ENTER")
                            time.sleep(0.3)
                            break
                    except Exception as e_enter:
                        self._debug_log(f"Error al abrir con ENTER '{termino}': {e_enter}")

                # Si no hubo coincidencia visible exacta, abrir primer resultado de búsqueda.
                if not chat_abierto and not abierto_por_enter:
                    if self._abrir_primer_resultado_busqueda(caja_busqueda, termino):
                        if self._esperar_chat_listo(timeout=8):
                            chat_abierto = True
                            print(f"  Grupo abierto por primer resultado: {termino}")
                            self._debug_log(f"Chat listo para grupo '{termino}' por primer resultado")
                            time.sleep(0.3)
                            break

                # Si ENTER no funcionó, intentar abrir por clic directo.
                if not chat_abierto and not abierto_por_enter and self._abrir_grupo_por_nombre(termino):
                    if self._esperar_chat_listo(timeout=8):
                        chat_abierto = True
                        print(f"  Grupo localizado con clic en búsqueda: {termino}")
                        self._debug_log(f"Chat listo para grupo '{termino}' con clic")
                        time.sleep(0.3)
                        break

                print(f"  No se pudo abrir el grupo: {termino}")
                self._debug_resultados_busqueda(termino)
                continue

            # Detectar rápido si WhatsApp dice "No se encontró"
            no_resultado = False
            try:
                WebDriverWait(self.driver, 1.5).until(
                    EC.presence_of_element_located((By.XPATH,
                        "//*[@data-testid='search-no-chats-or-contacts'] | "
                        "//span[contains(text(),'No se encontró ningún chat')]"
                    ))
                )
                no_resultado = True
                print(f"  Sin resultados para: {termino}, probando siguiente variante...")
            except:
                pass  # Sí hay resultados, continuar

            if no_resultado:
                continue

            # Intentar click en el resultado exacto cuando es grupo o nombre de chat
            if not es_numero and self._seleccionar_resultado_visible(termino):
                try:
                    WebDriverWait(self.driver, 2.5).until(
                        EC.presence_of_element_located((By.XPATH, "//footer"))
                    )
                    titulo_abierto = self._obtener_titulo_chat_abierto()
                    if self._coincide_titulo(destino_texto, titulo_abierto):
                        chat_abierto = True
                        print(f"  Grupo localizado con búsqueda: {termino}")
                        time.sleep(0.3)
                        break
                    print(f"  Resultado visible no coincide con '{termino}' (abierto: '{titulo_abierto}'), ignorando.")
                except:
                    pass

            # Intentar click en el primer resultado encontrado
            # Los contactos usan role="listitem"; los grupos usan data-testid="cell-frame-container"
            xpaths_resultado = [
                f"//div[@id='pane-side']//span[@title='{termino}']/ancestor::div[@data-testid='cell-frame-container'][1]",
                f"//div[@id='pane-side']//span[contains(@title,'{termino}')]/ancestor::div[@data-testid='cell-frame-container'][1]",
                f"//div[@id='pane-side']//span[@title='{termino}']/ancestor::div[@role='listitem'][1]",
                f"//div[@id='pane-side']//span[contains(@title,'{termino}')]/ancestor::div[@role='listitem'][1]",
                f"//div[@id='pane-side']//div[@data-testid='cell-frame-container'][.//span[@title='{termino}']]",
                f"//div[@id='pane-side']//div[@role='listitem'][.//span[@title='{termino}']]",
                f"//div[@id='pane-side']//span[@title='{termino}']",
                f"//div[@id='pane-side']//span[contains(@title,'{termino}')]",
            ]

            for xpath in xpaths_resultado:
                try:
                    primer_resultado = WebDriverWait(self.driver, 0.5).until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
                    self.driver.execute_script("arguments[0].click();", primer_resultado)
                    WebDriverWait(self.driver, 2.5).until(
                        EC.presence_of_element_located((By.XPATH, "//footer"))
                    )
                    if es_numero:
                        chat_abierto = True
                        print(f"  Contacto localizado con búsqueda: {termino}")
                        time.sleep(0.3)
                        break
                    else:
                        # Para grupos/nombres validar que se abrió el chat correcto
                        titulo_abierto = self._obtener_titulo_chat_abierto()
                        if self._coincide_titulo(destino_texto, titulo_abierto):
                            chat_abierto = True
                            print(f"  Grupo localizado con búsqueda: {termino}")
                            time.sleep(0.3)
                            break
                        else:
                            print(f"  Resultado no coincide con '{termino}' (abierto: '{titulo_abierto}'), ignorando.")
                            continue
                except:
                    continue

            if not chat_abierto:
                # Fallback: abrir con ENTER
                try:
                    caja_busqueda.send_keys(Keys.ENTER)
                    WebDriverWait(self.driver, 3).until(
                        EC.presence_of_element_located((By.XPATH, "//footer"))
                    )
                    chat_abierto = True
                    print(f"  Contacto abierto con ENTER usando: {termino}")
                    time.sleep(0.3)
                except:
                    pass

            if chat_abierto:
                break

        if not chat_abierto:
            if es_numero:
                # Último recurso para números: usar el chat activo que esté abierto
                print(f"  No se encontró {numero_limpio}. Intentando enviar al chat activo actual...")
                caja_busqueda.send_keys(Keys.ESCAPE)
                time.sleep(0.5)
                try:
                    WebDriverWait(self.driver, 4).until(
                        EC.presence_of_element_located((By.XPATH, "//footer"))
                    )
                    print(f"  Usando chat activo como destino (fallback).")
                except:
                    raise Exception(f"No se encontró el contacto {numero_limpio} y no hay chat activo abierto")
            else:
                raise Exception(f"No se encontró el grupo o chat '{destino_texto}'")

        return True

    def _pegar_mensaje(self, mensaje, rapido=False):
        """
        Busca la caja de texto del chat abierto, pega el mensaje y lo envía.
        """
        self._debug_log(f"Intentando escribir mensaje de {len(str(mensaje))} caracteres")
        if rapido:
            xpaths_input = [
                "//div[@data-testid='conversation-compose-box-input']",
                "//footer//div[@contenteditable='true'][@role='textbox']",
                "//footer//div[@data-lexical-editor='true']",
            ]
        else:
            xpaths_input = [
                "//div[@data-testid='conversation-compose-box-input']",
                "//div[@aria-label='Escribe un mensaje aquí']",
                "//div[@aria-label='Type a message']",
                "//footer//div[@contenteditable='true'][@role='textbox']",
                "//footer//div[@data-lexical-editor='true']",
                "//footer//div[@contenteditable='true']",
                "//div[@contenteditable='true'][@data-tab='10']",
                "//div[@contenteditable='true'][@role='textbox']",
            ]

        caja_texto = None
        xpath_encontrado = None
        for xpath in xpaths_input:
            try:
                caja_texto = WebDriverWait(self.driver, 0.8 if rapido else 2).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                xpath_encontrado = xpath
                break
            except:
                continue

        if not caja_texto:
            self._debug_log("No se encontró caja de texto para redactar mensaje")
            raise Exception("No se encontró la caja de texto del chat")

        self._debug_log(f"Caja de texto detectada con selector: {xpath_encontrado}")

        # Escribir el mensaje con efecto (rápido y natural)
        try:
            self.driver.execute_script("arguments[0].click(); arguments[0].focus();", caja_texto)
            time.sleep(0.08)
            self._escribir_mensaje_normal(caja_texto, mensaje)
            time.sleep(0.08)
            self._debug_log("Mensaje escrito en caja de texto")
        except Exception as e:
            self._debug_log(f"Error escribiendo mensaje carácter a carácter: {e}")
            try:
                caja_texto.send_keys(str(mensaje))
                time.sleep(0.2)
                self._debug_log("Mensaje escrito con fallback send_keys completo")
            except Exception as e2:
                self._debug_log(f"Fallback de escritura también falló: {e2}")
                raise Exception(f"No se pudo escribir el mensaje: {e2}")

        # Click en botón Enviar
        xpaths_enviar = [
            "//button[@data-testid='send']",
            "//button[@aria-label='Enviar']",
            "//button[@aria-label='Send']",
        ]

        for xpath in xpaths_enviar:
            try:
                btn_enviar = WebDriverWait(self.driver, 4).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                self.driver.execute_script("arguments[0].click();", btn_enviar)
                self._debug_log(f"Mensaje enviado con botón selector: {xpath}")
                return
            except Exception as e:
                self._debug_log(f"No se pudo usar botón enviar '{xpath}': {e}")
                continue

        # Fallback: tecla Enter
        try:
            caja_texto.send_keys(Keys.ENTER)
            self._debug_log("Mensaje enviado con fallback ENTER")
        except Exception as e:
            self._debug_log(f"Falló fallback ENTER: {e}")
            raise

    def enviar(self, id_registro, numero, mensaje, pantalla):
        """Flujo: buscar contacto → pegar mensaje → enviar"""
        self.actualizar_mensaje(id_registro, 'P')

        for intento in range(2):  # 1 intento normal + 1 reintento tras reconexión
            try:
                if not self._navegador_vivo():
                    self._reconectar()

                self._ensure_window_visible()
                self._ir_a_whatsapp()

                # Esperar que cargue la interfaz principal
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@id='side']"))
                )

                self._buscar_contacto(numero)
                numero_limpio = str(numero).replace("+", "").replace(" ", "").replace("-", "")
                es_numero = numero_limpio.isdigit()
                self._pegar_mensaje(mensaje, rapido=es_numero)

                time.sleep(1)
                self.actualizar_mensaje(id_registro, 'E')
                print(f" Mensaje enviado exitosamente a {numero}")
                return True

            except (WebDriverException, NoSuchWindowException, InvalidSessionIdException) as e:
                if intento == 0:
                    print(f" Navegador caído durante el envío. Reconectando...")
                    try:
                        self._reconectar()
                    except Exception as re:
                        error_msg = f"No se pudo reconectar: {re}"[:500]
                        print(f" {error_msg}")
                        self.actualizar_mensaje(id_registro, 'F', error_msg)
                        return False
                else:
                    error_msg = str(e)[:500]
                    print(f" Error al enviar a {numero} tras reconexión: {error_msg}")
                    self.actualizar_mensaje(id_registro, 'F', error_msg)
                    return False

            except Exception as e:
                error_msg = str(e)[:500]
                print(f" Error al enviar a {numero}: {error_msg}")
                self.actualizar_mensaje(id_registro, 'F', error_msg)
                return False

        return False

    # -------------------------------------------------------
    # Loop principal
    # -------------------------------------------------------
    def enviar_mensajes_pendientes(self):
        conn = self.cnx_empresas()
        if not conn:
            return

        try:
            cursor = conn.cursor()
            # Reglas de asignacion:
            # 1) Si numero_bot viene en BD (1 o 2), lo respeta.
            # 2) Si viene NULL o 0, se reparte entre bots por paridad de id.
            paridad_bot = self.bot_id % 2  # bot 1 -> 1 (impares), bot 2 -> 0 (pares)
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

            if not mensajes:
                hora_py = datetime.now().strftime("%H:%M:%S")
                print(f"NO HAY MENSAJES PENDIENTES - Bot {self.bot_id} - Hora: {hora_py}")
                return

            print(f"\n--- Bot {self.bot_id}: procesando {len(mensajes)} mensajes pendientes ---")

            for msg in mensajes:
                id_msg, numero, mensaje, pantalla = msg
                self.enviar(id_msg, numero, mensaje, pantalla)
                self._pausa_larga()   # delay aleatorio entre mensajes

        except Exception as e:
            print(f" Error procesando mensajes pendientes: {e}")

    def cerrar(self):
        if self.driver:
            try:
                self.driver.quit()
                print(" Navegador cerrado")
            except:
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
        args = parser.parse_args()

        bot_ids = [args.bot_id] if args.bot_id else [1, 2]
        for bot_id in bot_ids:
            bot = WhatsAppBotWeb(bot_id=bot_id)
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
            def enviar_horarioLaboral():
                ahora = datetime.now()
                if 8 <= ahora.hour < 17:
                    print(f"\n[{ahora.strftime('%Y-%m-%d %H:%M:%S')}] Ejecutando envío programado...")
                    with ThreadPoolExecutor(max_workers=len(bots)) as executor:
                        futures = [executor.submit(bot.enviar_mensajes_pendientes) for bot in bots]
                        for future in futures:
                            future.result()
                else:
                    print(f"[{ahora.strftime('%Y-%m-%d %H:%M:%S')}] Fuera de horario laboral.")

            print("Sistema iniciado. Horario laboral: 8:00 - 17:00")
            print("Ejecutando cada 30 minutos dentro del horario laboral...")
            print("=" * 50)

            while True:
                enviar_horarioLaboral()
                time.sleep(60)  # 1 minutos

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

        input("\nPresiona ENTER para salir...")
