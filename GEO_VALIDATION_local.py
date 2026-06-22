# ============================================================
# IMPORTS
# ============================================================
import os
import re
import ssl
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from io import BytesIO
from urllib.parse import quote
from urllib.request import urlopen

import certifi
import pandas as pd
import streamlit as st
from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef
from pyshacl import validate

# ============================================================
# CONSTANTES
# ============================================================

FORMAT_MAP = {
    ".ttl": "turtle",
    ".rdf": "xml",
    ".xml": "xml",
    ".jsonld": "json-ld",
}

TIPO_ERROR_MAP = {
    "ClassConstraintComponent": "Tipo de dato no permitido",
    "MinCountConstraintComponent": "Cardinalidad mínima obligatoria",
    "MaxCountConstraintComponent": "Supera Cardinalidad máxima",
    "DatatypeConstraintComponent": "Tipo de dato",
    "PatternConstraintComponent": "Patrón",
    "NodeKindConstraintComponent": "Tipo de nodo",
    "PropertyConstraintComponent": "Restricción de propiedad",
    "OrConstraintComponent": "Condición OR",
    "AndConstraintComponent": "Condición AND",
    "XoneConstraintComponent": "Condición XOR",
    "NotConstraintComponent": "Condición NOT",
}

BASE_DIR_SHACL = "Validacion"

VALIDACIONES = {
    "GEODCAT-AP": ["GEODCAT-AP"],
    "DCAT-AP-ES-HVD": ["DCAT-AP-ES", "DCAT-AP-ES-HVD"],
    "DCAT-AP-ES": "DCAT-AP-ES",
}

# XSLTs predefinidas alojadas en GitHub
XSLT_GITHUB = {
    "GeoDCAT-AP v7 (geodacat.v7)": "https://raw.githubusercontent.com/SEMICeu/iso-19139-to-dcat-ap/master/iso-19139-to-dcat-ap.xsl",
    "Subir XSLT manualmente": None,
}

SH = Namespace("http://www.w3.org/ns/shacl#")

# ============================================================
# FUNCIONES AUXILIARES COMPARTIDAS
# ============================================================

def short_name(uri):
    if not uri:
        return ""
    uri = str(uri)
    return uri.split("#")[-1] if "#" in uri else uri.split("/")[-1]


def escape_uri(uri):
    return quote(str(uri), safe=":/#")


def limpiar_uris_invalidas(content):
    return content.replace("{", "%7B").replace("}", "%7D")


def obtener_valor_metadato(g, focus, path, value):
    if value is not None:
        if isinstance(value, Literal):
            return str(value)
        if isinstance(value, URIRef):
            return escape_uri(value)
        if isinstance(value, BNode):
            return "Blank node"
    if focus and path and isinstance(path, URIRef):
        vals = list(g.objects(focus, path))
        if vals:
            return ", ".join(
                escape_uri(v) if isinstance(v, URIRef) else str(v) for v in vals
            )
    return "No encontrado"


def validar_rdf_individual(rdf_name, rdf_bytes, shapes_graph):
    """Valida bytes RDF frente a un grafo SHACL."""
    data_graph = Graph()
    ext = "." + rdf_name.split(".")[-1].lower()
    rdf_format = FORMAT_MAP.get(ext, "xml")

    content = rdf_bytes.decode("utf-8") if isinstance(rdf_bytes, bytes) else rdf_bytes
    content = limpiar_uris_invalidas(content)
    data_graph.parse(data=content, format=rdf_format)

    if len(data_graph) == 0:
        raise ValueError(f"RDF vacío: {rdf_name}")

    conforms, report_graph, _ = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        abort_on_first=False,
        advanced=True,
    )
    return data_graph, report_graph, conforms


def cargar_shapes(opcion_validacion):
    """Carga los shapes SHACL desde las carpetas configuradas."""
    shapes_graph = Graph()
    seleccion = VALIDACIONES[opcion_validacion]
    carpetas = seleccion if isinstance(seleccion, list) else [seleccion]

    for carpeta in carpetas:
        ruta_carpeta = os.path.join(BASE_DIR_SHACL, carpeta)
        if not os.path.exists(ruta_carpeta):
            st.error(f"❌ No existe la carpeta SHACL: {ruta_carpeta}")
            st.stop()
        for archivo in os.listdir(ruta_carpeta):
            if archivo.endswith(".ttl"):
                shapes_graph.parse(
                    os.path.join(ruta_carpeta, archivo), format="turtle"
                )
    return shapes_graph


def mostrar_resultados_validacion(results):
    """Renderiza tablas de resumen y detalle de validación SHACL."""

    # --- Resumen global por RDF ---
    resumen_rdf = []
    for rdf_name, (data_graph, report_graph, conforms) in results:
        errores = warnings = 0
        metadatos_unicos = set()
        for r in report_graph.subjects(RDF.type, SH.ValidationResult):
            path = report_graph.value(r, SH.resultPath)
            severity = report_graph.value(r, SH.resultSeverity)
            if path:
                metadatos_unicos.add(short_name(path))
            if severity == SH.Violation:
                errores += 1
            elif severity == SH.Warning:
                warnings += 1
        resumen_rdf.append(
            {
                "RDF": rdf_name,
                "Estado": "✅ CUMPLE" if errores == 0 else "❌ NO CUMPLE",
                "Errores": errores,
                "Warnings": warnings,
                "Metadatos únicos afectados": len(metadatos_unicos),
            }
        )

    st.markdown("---")
    st.header("📊 Resumen por RDF")
    df_resumen = pd.DataFrame(resumen_rdf)
    df_resumen.index += 1
    st.dataframe(df_resumen, use_container_width=True)

    # --- Filtro de severidad ---
    st.markdown("---")
    st.header("🎛️ Filtro de Severidad")

    if "filtro_severidad" not in st.session_state:
        st.session_state["filtro_severidad"] = ["ERROR", "WARNING", "INFO"]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("Todos", key="sev_all"):
            st.session_state["filtro_severidad"] = ["ERROR", "WARNING", "INFO"]
    with col2:
        if st.button("❌ Errores", key="sev_err"):
            st.session_state["filtro_severidad"] = ["ERROR"]
    with col3:
        if st.button("⚠️ Warnings", key="sev_warn"):
            st.session_state["filtro_severidad"] = ["WARNING"]
    with col4:
        if st.button("ℹ️ Info", key="sev_info"):
            st.session_state["filtro_severidad"] = ["INFO"]

    filtro_severidad = st.session_state.get(
        "filtro_severidad", ["ERROR", "WARNING", "INFO"]
    )

    # --- Detalle por RDF ---
    for rdf_name, (data_graph, report_graph, conforms) in results:
        errores_rdf = sum(
            1
            for r in report_graph.subjects(RDF.type, SH.ValidationResult)
            if report_graph.value(r, SH.resultSeverity) == SH.Violation
        )
        estado = "✅ CUMPLE" if errores_rdf == 0 else "❌ NO CUMPLE"

        st.markdown("---")
        with st.expander(f"📂 {rdf_name} — {estado}", expanded=True):

            errores_por_clase = defaultdict(list)
            resumen_path = defaultdict(int)
            resumen_tipo = defaultdict(lambda: {"total": 0, "paths": set()})

            for r in report_graph.subjects(RDF.type, SH.ValidationResult):
                focus = report_graph.value(r, SH.focusNode)
                path = report_graph.value(r, SH.resultPath)
                value = report_graph.value(r, SH.value)
                message = report_graph.value(r, SH.resultMessage)
                constraint = report_graph.value(r, SH.sourceConstraintComponent)
                severity = report_graph.value(r, SH.resultSeverity)

                sev_uri = str(severity)
                if "Violation" in sev_uri:
                    sev_text = "ERROR"
                elif "Warning" in sev_uri:
                    sev_text = "WARNING"
                else:
                    sev_text = "INFO"

                if sev_text not in filtro_severidad:
                    continue

                tipo_error = TIPO_ERROR_MAP.get(
                    short_name(constraint), short_name(constraint)
                )
                path_legible = short_name(path)

                resumen_path[path_legible] += 1
                resumen_tipo[tipo_error]["total"] += 1
                resumen_tipo[tipo_error]["paths"].add(path_legible)

                types = list(data_graph.objects(focus, RDF.type))
                clase = "Desconocido"
                for t in types:
                    if "dcat" in str(t).lower():
                        clase = short_name(t)
                        break
                if clase == "Desconocido" and types:
                    clase = short_name(types[0])

                errores_por_clase[clase].append(
                    {
                        "Severidad": sev_text,
                        "Tipo de error": tipo_error,
                        "Mensaje": str(message),
                        "Metadato": path_legible,
                        "Valor": obtener_valor_metadato(
                            data_graph, focus, path, value
                        ),
                        "FocusNode": str(focus),
                    }
                )

            # Resumen por metadato
            st.subheader("📊 Resumen por Metadato")
            df_path = pd.DataFrame(
                [{"Metadato": k, "Total errores": v} for k, v in resumen_path.items()]
            )
            if df_path.empty:
                st.info("No hay datos para mostrar en el resumen por metadato")
            else:
                df_path.index += 1
                st.dataframe(df_path, use_container_width=True)

            # Resumen por tipo de error
            st.subheader("📊 Resumen por Tipo de Error")
            df_tipo = pd.DataFrame(
                [
                    {
                        "Tipo de Error": t,
                        "Errores únicos (metadatos)": len(v["paths"]),
                        "Total Errores": v["total"],
                    }
                    for t, v in resumen_tipo.items()
                ]
            )
            if df_tipo.empty:
                st.info("No hay datos para mostrar en el resumen por tipo de error")
            else:
                df_tipo.index += 1
                st.dataframe(df_tipo, use_container_width=True)

            # Filtro por clase
            clases_disponibles = sorted(errores_por_clase.keys())
            st.markdown("---")
            st.header("🎛️ Filtro por Clase")
            clase_seleccionada = st.selectbox(
                "Selecciona una clase:",
                ["Todas"] + clases_disponibles,
                key=f"select_clase_{rdf_name}",
            )

            st.subheader("📋 Detalle de Errores por Clase")
            clases_a_mostrar = (
                errores_por_clase.items()
                if clase_seleccionada == "Todas"
                else [(clase_seleccionada, errores_por_clase.get(clase_seleccionada, []))]
            )
            for clase, errores_lista in clases_a_mostrar:
                st.markdown(f"### 🧱 Clase: `{clase}`")
                df_det = pd.DataFrame(errores_lista)
                if df_det.empty:
                    st.info("Sin errores en esta clase")
                else:
                    df_det.index += 1
                    st.dataframe(df_det, use_container_width=True)


# ============================================================
# CONFIGURACIÓN STREAMLIT
# ============================================================
st.set_page_config(page_title="Transformador & Validador SHACL", layout="wide")
st.title("🗺️ Transformador XML→RDF & Validador SHACL — Proyecto GDDP")

# --- Reset global ---
top1, top2 = st.columns([8, 1])
with top2:
    if st.button("🔄 Reset"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# Inicializar estado
for key, default in [
    ("run_validation", False),
    ("file_uploader_counter", 0),
    ("rdfs_transformados", {}),   # {nombre: bytes_rdf}
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ============================================================
# TABS PRINCIPALES
# ============================================================
tab_transform, tab_validate = st.tabs(
    ["🔄 Transformar XML → RDF", "✅ Validar RDF (SHACL)"]
)

# ============================================================
# TAB 1 — TRANSFORMACIÓN XML → RDF
# ============================================================
with tab_transform:
    st.header("Transformación XML INSPIRE/ISO → RDF")
    st.markdown(
        "Sube uno o varios XML en formato INSPIRE/ISO 19139 y conviértelos a RDF "
        "usando una hoja XSLT. Los RDF generados podrán validarse directamente en la pestaña de validación."
    )

    # --- Origen XML ---
    xml_source_option = st.radio(
        "Origen de los XML",
        ["Subir archivos XML", "URLs de XML"],
        horizontal=True,
    )

    xml_files_uploaded = []
    xml_urls = []

    if xml_source_option == "Subir archivos XML":
        xml_files_uploaded = st.file_uploader(
            "📂 Selecciona uno o varios XML",
            type=["xml"],
            accept_multiple_files=True,
            key=f"xml_up_{st.session_state['file_uploader_counter']}",
        )
    else:
        xml_urls_text = st.text_area("Introduce URLs XML (una por línea)")
        xml_urls = [l.strip() for l in xml_urls_text.splitlines() if l.strip()]

    # --- Selección XSLT ---
    st.markdown("---")
    st.subheader("Hoja XSLT")

    xslt_opcion = st.selectbox("Elige la XSLT:", list(XSLT_GITHUB.keys()))
    xslt_url_github = XSLT_GITHUB[xslt_opcion]

    xslt_manual = None
    if xslt_url_github is None:
        xslt_manual = st.file_uploader(
            "Sube tu XSLT",
            type=["xsl", "xslt"],
            key=f"xslt_up_{st.session_state['file_uploader_counter']}",
        )
    else:
        st.info(f"Se usará la XSLT desde GitHub:\n`{xslt_url_github}`")

        # Permitir también especificar una URL personalizada
        xslt_custom_url = st.text_input(
            "O introduce otra URL de XSLT (opcional, sobreescribe la selección):",
            placeholder="https://raw.githubusercontent.com/...",
        )
        if xslt_custom_url.strip():
            xslt_url_github = xslt_custom_url.strip()

    # --- Botón Transformar ---
    st.markdown("---")
    if st.button("🚀 Transformar"):

        # Validaciones previas
        if xslt_url_github is None and xslt_manual is None:
            st.error("Debes seleccionar o subir una XSLT.")
            st.stop()
        if xml_source_option == "Subir archivos XML" and not xml_files_uploaded:
            st.error("Debes subir al menos un XML.")
            st.stop()
        if xml_source_option == "URLs de XML" and not xml_urls:
            st.error("Debes introducir al menos una URL.")
            st.stop()

        # Importar SaxonC
        try:
            from saxonche import PySaxonProcessor
        except Exception as e:
            st.error(f"Error cargando SaxonC HE: {e}")
            st.stop()

        with st.spinner("Procesando..."):

            # --- Obtener bytes XSLT ---
            try:
                if xslt_url_github:
                    ctx = ssl.create_default_context(cafile=certifi.where())
                    xslt_bytes = urlopen(xslt_url_github, context=ctx).read()
                    st.success(f"XSLT descargada desde GitHub.")
                else:
                    xslt_bytes = xslt_manual.getvalue()
                    st.success("XSLT cargada desde archivo local.")
            except Exception as e:
                st.error(f"No se pudo obtener la XSLT: {e}")
                st.stop()

            # --- Guardar XSLT temporal y compilar ---
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".xsl", mode="wb"
            ) as tmp_xsl:
                tmp_xsl.write(xslt_bytes)
                tmp_xsl_path = tmp_xsl.name

            processor = PySaxonProcessor(license=False)
            xslt_processor = processor.new_xslt30_processor()
            try:
                executable = xslt_processor.compile_stylesheet(
                    stylesheet_file=tmp_xsl_path
                )
            except Exception as e:
                st.error(f"Error compilando XSLT: {e}")
                st.stop()

            # --- Preparar lista de XMLs ---
            xml_list = []
            if xml_source_option == "Subir archivos XML":
                for f in xml_files_uploaded:
                    xml_list.append((f.name, f.getvalue()))
            else:
                ctx = ssl.create_default_context(cafile=certifi.where())
                for url in xml_urls:
                    try:
                        content = urlopen(url, context=ctx).read()
                        fname = url.split("/")[-1] or "dataset.xml"
                        xml_list.append((fname, content))
                    except Exception as e:
                        st.error(f"Error descargando {url}: {e}")

            if not xml_list:
                st.error("No hay XMLs válidos para procesar.")
                st.stop()

            progress = st.progress(0)
            rdfs_nuevos = {}

            for i, (original_name, xml_content) in enumerate(xml_list):
                st.divider()
                st.subheader(f"📄 {original_name}")

                # Guardar XML temporal
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".xml", mode="wb"
                ) as tmp_xml:
                    tmp_xml.write(xml_content)
                    tmp_xml_path = tmp_xml.name

                # Transformar
                try:
                    rdf_result = executable.transform_to_string(
                        source_file=tmp_xml_path
                    )
                except Exception as e:
                    st.error(f"Error en transformación XSLT: {e}")
                    progress.progress((i + 1) / len(xml_list))
                    continue

                if not rdf_result:
                    st.error("La transformación no devolvió contenido.")
                    progress.progress((i + 1) / len(xml_list))
                    continue

                # Extraer título del XML ISO
                title_text = original_name.replace(".xml", "")
                try:
                    root = ET.fromstring(xml_content)
                    ns = {
                        "gmd": "http://www.isotc211.org/2005/gmd",
                        "gco": "http://www.isotc211.org/2005/gco",
                    }
                    el = root.find(
                        ".//gmd:identificationInfo//gmd:citation//gmd:title/gco:CharacterString",
                        ns,
                    )
                    if el is not None and el.text:
                        raw = unicodedata.normalize("NFKD", el.text.strip())
                        raw = raw.encode("ASCII", "ignore").decode("utf-8")
                        title_text = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
                        title_text = re.sub(r"_+", "_", title_text)[:100]
                except Exception:
                    pass

                rdf_filename = f"{title_text}.rdf"
                rdf_bytes = rdf_result.encode("utf-8")

                # Guardar en sesión para el validador
                rdfs_nuevos[rdf_filename] = rdf_bytes
                st.session_state["rdfs_transformados"][rdf_filename] = rdf_bytes

                # Vista previa
                st.success(f"✅ RDF generado: `{rdf_filename}`")
                preview = rdf_result[:3000] + ("..." if len(rdf_result) > 3000 else "")
                st.code(preview, language="xml")

                # Descarga individual
                st.download_button(
                    label=f"⬇️ Descargar {rdf_filename}",
                    data=rdf_bytes,
                    file_name=rdf_filename,
                    mime="application/rdf+xml",
                    key=f"dl_{rdf_filename}_{i}",
                )

                progress.progress((i + 1) / len(xml_list))

            if rdfs_nuevos:
                st.success(
                    f"✅ {len(rdfs_nuevos)} RDF(s) generados y disponibles en la pestaña **✅ Validar RDF**."
                )

# ============================================================
# TAB 2 — VALIDACIÓN SHACL
# ============================================================
with tab_validate:
    st.header("Validación SHACL — DCAT-AP-ES / GeoDCAT-AP")

    # --- Fuentes de RDF: subidos + generados en tab1 ---
    st.markdown("#### 📂 RDF a validar")

    rdf_files_upload = st.file_uploader(
        "Subir archivos RDF directamente",
        type=["rdf", "xml", "ttl", "jsonld"],
        accept_multiple_files=True,
        key=f"val_rdf_{st.session_state['file_uploader_counter']}",
    )

    # Mostrar RDFs generados en la transformación
    rdfs_sesion = st.session_state.get("rdfs_transformados", {})
    if rdfs_sesion:
        st.markdown("**RDFs disponibles desde la transformación:**")
        rdfs_seleccionados = {}
        for nombre in rdfs_sesion:
            check = st.checkbox(f"✅ {nombre}", value=True, key=f"chk_{nombre}")
            if check:
                rdfs_seleccionados[nombre] = rdfs_sesion[nombre]
    else:
        rdfs_seleccionados = {}
        st.info(
            "💡 También puedes generar RDFs automáticamente desde la pestaña **🔄 Transformar XML → RDF**."
        )

    # --- Validación SHACL ---
    st.markdown("---")
    st.markdown("#### 🔍 Configuración de validación")
    opcion_validacion = st.selectbox(
        "Elige el conjunto de validaciones SHACL:",
        list(VALIDACIONES.keys()),
        key="val_shacl_select",
    )

    if st.button("🚀 Ejecutar validación", key="btn_validar"):
        st.session_state["run_validation"] = True
        st.session_state["results"] = None

    if st.session_state.get("run_validation"):

        # Combinar fuentes RDF
        fuentes_rdf = []  # lista de (nombre, bytes)

        for f in (rdf_files_upload or []):
            fuentes_rdf.append((f.name, f.getvalue()))

        for nombre, rb in rdfs_seleccionados.items():
            fuentes_rdf.append((nombre, rb))

        if not fuentes_rdf:
            st.warning("⚠️ No hay RDF seleccionados para validar.")
            st.stop()

        if st.session_state.get("results") is None:

            with st.spinner("📘 Cargando shapes SHACL..."):
                shapes_graph = cargar_shapes(opcion_validacion)

            results = []
            progress = st.progress(0, text="⏳ Iniciando validación...")
            total = len(fuentes_rdf)

            for i, (rdf_name, rdf_bytes) in enumerate(fuentes_rdf):
                progress.progress(i / total, text=f"⏳ Validando: {rdf_name}")
                try:
                    data_graph, report_graph, conforms = validar_rdf_individual(
                        rdf_name, rdf_bytes, shapes_graph
                    )
                    results.append((rdf_name, (data_graph, report_graph, conforms)))
                except Exception as e:
                    st.error(f"❌ Error procesando '{rdf_name}': {e}")
                    st.stop()

            progress.progress(1.0, text="✅ Validación completada")
            st.session_state["results"] = results

        mostrar_resultados_validacion(st.session_state["results"])
