# ------------------------------------------------------------
# IMPORTS
# ------------------------------------------------------------
from collections import defaultdict
from urllib.parse import quote

from rdflib import RDF, Namespace, URIRef, Literal, BNode, Graph
from pyshacl import validate
import streamlit as st
import pandas as pd
import os
# ------------------------------------------------------------
# MAPEO CONSTANTES (DICCIONARIOS)
# ------------------------------------------------------------
FORMAT_MAP = {
    ".ttl": "turtle",
    ".rdf": "xml",
    ".xml": "xml",
    ".jsonld": "json-ld"
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
    "NotConstraintComponent": "Condición NOT"
}
BASE_DIR_SHACL = "Validacion"

VALIDACIONES = {
    "DCAT-AP-ES": "DCAT-AP-ES",
    "DCAT-AP-ES-HVD": ["DCAT-AP-ES", "DCAT-AP-ES-HVD"]
}

SH = Namespace("http://www.w3.org/ns/shacl#")

# ------------------------------------------------------------
# FUNCIONES AUXILIARES
# ------------------------------------------------------------
def short_name(uri):
    """Devuelve la parte final de una URI para mostrar en resúmenes y tablas."""
    if not uri:
        return ""
    uri = str(uri)
    return uri.split("#")[-1] if "#" in uri else uri.split("/")[-1]

def escape_uri(uri):
    """Escapa una URI para que sea válida en Turtle/SHACL."""
    return quote(str(uri), safe=":/#")

def limpiar_uris_invalidas(content):
    return content.replace("{", "%7B").replace("}", "%7D")

def obtener_valor_metadato(g, focus, path, value):
    """Obtiene el valor legible de un metadato, URI o literal."""
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
                escape_uri(v) if isinstance(v, URIRef) else str(v)
                for v in vals
            )
    return "No encontrado"

def validar_rdf_individual(rdf_file, shapes_graph):
    """Valida un RDF frente a un grafo SHACL. Lanza excepción si hay error."""
    data_graph = Graph()
    ext = "." + rdf_file.name.split(".")[-1].lower()
    rdf_format = FORMAT_MAP.get(ext)

    if not rdf_format:
        raise ValueError(f"Formato RDF no soportado: {ext}")

    content = rdf_file.getvalue()
    if isinstance(content, bytes):
        content = content.decode("utf-8")

    content = limpiar_uris_invalidas(content)
    data_graph.parse(data=content, format=rdf_format)

    if len(data_graph) == 0:
        raise ValueError(f"RDF vacío: {rdf_file.name}")

    conforms, report_graph, _ = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        abort_on_first=False,
        advanced=True
    )

    return rdf_file.name, (data_graph, report_graph, conforms)

# ------------------------------------------------------------
# CONFIGURACIÓN STREAMLIT
# ------------------------------------------------------------
st.set_page_config(page_title="Validador SHACL", layout="wide")
st.title("Validador SHACL- DCAT-AP-ES - Proyecto GDDP")

# Inicializar estado
if "run_validation" not in st.session_state:
    st.session_state["run_validation"] = False
if "file_uploader_counter" not in st.session_state:
    st.session_state["file_uploader_counter"] = 0

# ------------------------------------------------------------
# BOTÓN RESET
# ------------------------------------------------------------
top1, top2 = st.columns([8, 1])
with top2:
    reset = st.button("🔄 Reset")

if reset:
    st.session_state["run_validation"] = False
    st.session_state["results"] = None
    for key in list(st.session_state.keys()):
        if key not in ["run_validation", "file_uploader_counter"]:
            del st.session_state[key]
    st.session_state["file_uploader_counter"] += 1
    st.rerun()

# ------------------------------------------------------------
# SUBIDA DE ARCHIVOS
# ------------------------------------------------------------
DATA_FILE = st.file_uploader(
    "📂 Subir archivos RDF",
    type=["rdf", "xml"],
    accept_multiple_files=True,
    key=f"data_file_{st.session_state['file_uploader_counter']}"
)

st.markdown("📘 Seleccionar validación SHACL")

opcion_validacion = st.selectbox(
    "Elige un conjunto de validaciones:",
    list(VALIDACIONES.keys())
)

if st.button("🚀 Ejecutar validación"):
    st.session_state["run_validation"] = True
    st.session_state["results"] = None

# ------------------------------------------------------------
# VALIDACIÓN (solo se ejecuta cuando se da al botón)
# ------------------------------------------------------------
if st.session_state["run_validation"]:

    if not DATA_FILE:
        st.warning("⚠️ Debes subir RDF antes de validar")
        st.stop()

    # Solo ejecutar si aún no hay resultados
    if st.session_state["results"] is None:

        # Cargar shapes desde carpetas
        shapes_graph = Graph()

        with st.spinner("📘 Cargando Shapes SHACL..."):

            seleccion = VALIDACIONES[opcion_validacion]

            if isinstance(seleccion, list):
                carpetas = seleccion
            else:
                carpetas = [seleccion]

            for carpeta in carpetas:
                ruta_carpeta = os.path.join(BASE_DIR_SHACL, carpeta)

                if not os.path.exists(ruta_carpeta):
                    st.error(f"❌ No existe la carpeta: {ruta_carpeta}")
                    st.stop()

                for archivo in os.listdir(ruta_carpeta):
                    if archivo.endswith(".ttl"):
                        ruta = os.path.join(ruta_carpeta, archivo)
                        shapes_graph.parse(ruta, format="turtle")

        # Validación
        results = []
        progress = st.progress(0, text="⏳ Iniciando validación...")
        total = len(DATA_FILE)

        for i, f in enumerate(DATA_FILE):
            progress.progress((i) / total, text=f"⏳ Validando: {f.name}")
            try:
                name, resultado = validar_rdf_individual(f, shapes_graph)
                results.append((name, resultado))
            except Exception as e:
                st.error(f"❌ Error procesando '{f.name}': {e}")
                st.stop()

        progress.progress(1.0, text="✅ Validación completada")

        st.session_state["results"] = results
        st.session_state["shapes_graph"] = shapes_graph

    # ------------------------------------------------------------
    # MOSTRAR RESULTADOS (siempre, usando sesión, se almacenan en el cache)
    # ------------------------------------------------------------
    results = st.session_state.get("results", [])

    # Resumen global
    resumen_global = {"rdf": [], "errores": 0, "warnings": 0}
    resumen_rdf = []

    for rdf_name, resultado in results:
        data_graph, report_graph, conforms = resultado
        errores = 0
        warnings = 0
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
        if errores == 0:
            estado = "✅ CUMPLE"
        else:
            estado = "❌ NO CUMPLE"            
            
        resumen_rdf.append({
            "RDF": rdf_name,
            "Estado": estado,
            "Errores": errores,
            "Warnings": warnings,
            "Metadatos únicos afectados": len(metadatos_unicos)
        })
        resumen_global["errores"] += errores
        resumen_global["warnings"] += warnings
        resumen_global["rdf"].append(rdf_name)

    # Tabla resumen
    st.markdown("---")
    st.header("📊 Resumen por RDF")
    df_resumen_rdf = pd.DataFrame(resumen_rdf)
    df_resumen_rdf.index += 1
    st.dataframe(df_resumen_rdf, width='content')

    # Métricas globales
    col1, col2, col3 = st.columns(3)
    col1.metric("❌ Errores SHACL", resumen_global["errores"])
    col2.metric("⚠️ Warnings SHACL", resumen_global["warnings"])
    col3.metric("📄 RDF validados", len(resumen_global["rdf"]))

    # ------------------------------------------------------------
    # FILTRO DE SEVERIDAD
    # ------------------------------------------------------------
    st.markdown("---")
    st.header("🎛️ Filtro de Severidad")

    filtro = st.radio(
        "Filtrar por:",
        ["Todos", "Solo errores", "Solo warnings", "Solo info"]
    )
    
    if filtro == "Todos":
        filtro_severidad = ["ERROR", "WARNING", "INFO"]
    elif filtro == "Solo errores":
        filtro_severidad = ["ERROR"]
    elif filtro == "Solo warnings":
        filtro_severidad = ["WARNING"]
    else:
        filtro_severidad = ["INFO"]

    #-----------------------------------------------------------
    # RESULTADOS DETALLADOS POR RDF
    # ------------------------------------------------------------
    for rdf_name, resultado in results:
        data_graph, report_graph, conforms = resultado
    
        # 👇 AÑADIR ESTO
        errores = 0
        warnings = 0
    
        for r in report_graph.subjects(RDF.type, SH.ValidationResult):
            severity = report_graph.value(r, SH.resultSeverity)
            if severity == SH.Violation:
                errores += 1
            elif severity == SH.Warning:
                warnings += 1
    
        if errores == 0:
            estado = "✅ CUMPLE"
        else:
           estado = "❌ NO CUMPLE"
            
        st.markdown("---")
        with st.expander(
            f"📂 {rdf_name} — {estado}",
            expanded=True
        ):
            # Descarga TTL
            try:
                ttl = report_graph.serialize(format="turtle")
                if isinstance(ttl, bytes):
                    ttl = ttl.decode("utf-8")

                st.download_button(
                    f"⬇️ Descargar TTL ({rdf_name})",
                    ttl,
                    f"validation_report_{rdf_name}.ttl",
                    "text/turtle"
                )
                with st.expander("📄 Ver reporte TTL"):
                    st.code(ttl, language="turtle")
            except Exception as e:
                st.warning(f"No se pudo generar TTL: {e}")

            # Parseo de errores
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

                sev_text = (
                    "ERROR" if severity == SH.Violation
                    else "WARNING" if severity == SH.Warning
                    else "INFO"
                )

                if sev_text not in filtro_severidad:
                    continue

                tipo_error = TIPO_ERROR_MAP.get(short_name(constraint), short_name(constraint))
                path_legible = short_name(path)

                resumen_path[path_legible] += 1
                resumen_tipo[tipo_error]["total"] += 1
                resumen_tipo[tipo_error]["paths"].add(path_legible)

                types = list(report_graph.objects(focus, RDF.type))
                clase = short_name(types[0]) if types else "Desconocido"

                errores_por_clase[clase].append({
                    "Severidad": sev_text,
                    "Tipo de error": tipo_error,
                    "Mensaje": str(message),
                    "Metadato": path_legible,
                    "Valor": obtener_valor_metadato(data_graph, focus, path, value),
                    "FocusNode": str(focus)
                })

            # Tablas detalladas
            st.subheader("📊 Resumen por Metadato")
            df_path = pd.DataFrame([{"Metadato": k, "Total errores": v} for k, v in resumen_path.items()])
            df_path.index += 1
            st.dataframe(df_path)

            st.subheader("📊 Resumen por Tipo de Error")
            df_tipo = pd.DataFrame([{
                "Tipo de Error": t,
                "Errores únicos (metadatos)": len(v["paths"]),
                "Total Errores": v["total"]
            } for t, v in resumen_tipo.items()])
            df_tipo.index += 1
            st.dataframe(df_tipo)

            st.subheader("📋 Detalle de Errores por Clase")
            for clase, errores_lista in errores_por_clase.items():
                st.markdown(f"### 🧱 Clase: `{clase}`")
                df_det = pd.DataFrame(errores_lista)
                df_det.index += 1
                st.dataframe(df_det, width='content')
