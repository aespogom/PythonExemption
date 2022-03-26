import datetime
import logging
import random
import string
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.contrib.humanize.templatetags.humanize import intcomma
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.template.defaulttags import register

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.platypus import Image, HRFlowable

from reportlab.pdfbase import pdfmetrics

import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg
import numpy as np

from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('SourceSans', './main/static/ttf/SourceSansPro-Regular.ttf'))
pdfmetrics.registerFont(TTFont('SourceSansBol', './main/static/ttf/SourceSansPro-Bold.ttf'))
#pdfmetrics.registerFont(TTFont('SabonIta', 'SabonIta.ttf'))
#pdfmetrics.registerFont(TTFont('SabonBolIta', 'SabonBolIta.ttf'))
from reportlab.lib.fonts import addMapping
addMapping('SourceSans', 0, 0, 'SourceSans') #normal
addMapping('SourceSans', 1, 0, 'SourceSansBol') #bold
#addMapping('Sabon', 0, 1, 'SabonIta') #italic
#addMapping('Sabon', 1, 1, 'SabonBolIta') #italic and bold

from main.models import Evaluacion, Empleados, PlantillaEvaluacion, Preguntas, Respuestas, Sueldos, Sueldos_propuestos
from main.static.fusioncharts import FusionCharts
from people.settings.base import ADMIN_USER_NAME

logger = logging.getLogger(__name__)
ANIO = datetime.datetime.now()

def buscar_siguiente_pregunta(id_preguntas, pregunta_actual):
    size = len(id_preguntas)
    i = 0
    found = False
    while not found and i < size:
        if id_preguntas[i] == int(pregunta_actual):
            found = True
        else:
            i += 1

    return id_preguntas[i + 1]


def comprobarIdPregunta(id_preguntas, pregunta_actual):
    size = len(id_preguntas)
    i = 0
    found = False
    while not found and i < size:
        if id_preguntas[i] == int(pregunta_actual):
            found = True
        else:
            i += 1
    return id_preguntas[i + 1]


@login_required(login_url='/accounts/login/')
def empleado_respuestas_verificar(request, id_evaluacion, id_empleado):
    context = dict()
    id_evaluacion = id_evaluacion
    id_empleado = id_empleado
    user_log = Empleados.objects.get(email=request.user.username)
    empleado = Empleados.objects.get(id_empleado=id_empleado)
    evaluacion = Evaluacion.objects.get(id_evaluacion=id_evaluacion)

    if evaluacion.responsable == user_log or user_log.resp_depart or evaluacion.empleado == user_log:
        preguntas = Preguntas.objects.filter(id_plantilla=evaluacion.id_plantilla)

        context['id_evaluacion'] = id_evaluacion
        context['id_empleado'] = id_empleado
        context['user_nombre'] = user_log.nombre + ' ' + user_log.apellidos
        context['emp_nombre'] = empleado.nombre + ' ' + empleado.apellidos

        context['identificador'] = user_log.id_empleado
        context['name_menu'] = user_log.nombre

        if user_log.evaluador or user_log.resp_depart or user_log.email == 'admin':
            context['menu'] = True
        if user_log.ver_sueldos:
            context['ver_sueldo'] = True

        if evaluacion.id_plantilla.autoevaluacion:
            context['tipo'] = 'empleado'
        else:
            context['tipo'] = 'responsable'

        for pregunta in preguntas:
            try:
                Respuestas.objects.get(id_pregunta=pregunta.id_pregunta, id_evaluacion=id_evaluacion)
                contestadas = True
            except Respuestas.DoesNotExist:
                context['msg'] = "No has contestado todas las preguntas"
                return render(request, 'empleado/respuestas.html', context)
        if contestadas:
            Evaluacion.objects.filter(id_evaluacion=id_evaluacion).update(verificado=True,
                                                                          fecha_verificado=datetime.date.today())  # Actualizar estado evaluacion
            context[
                'msg'] = "Has verificado todas las respuestas de la evaluación, " + evaluacion.id_plantilla.descripcion

            return render(request, 'empleado/respuestas.html', context)
    else:
        return '404.html'


def calcularProgreso(empleado):
    fecha = datetime.datetime.now()
    try:
        plantilla_eval = PlantillaEvaluacion.objects.filter(autoevaluacion=False, de_responsable=False)
        evaluaciones_verificadas = len(Evaluacion.objects.filter(responsable=empleado, verificado=True, anio=fecha.year,
                                                                 id_plantilla__in=plantilla_eval))
        if evaluaciones_verificadas:
            progreso = evaluaciones_verificadas
        else:
            progreso = 0
        return progreso
    except Exception as e:
        logger.debug("Error al calcular progreso", e)
        return 0


def calcularSMax(empleado):
    sueldo_max = 0
    anio_actual = datetime.datetime.now()
    if empleado.resp_depart:
        sueldos = Sueldos.objects.filter(anio=anio_actual.year,
                                         empleado__in=Empleados.objects.filter(area_empleado=empleado.area_empleado))
    else:
        sueldos = Sueldos.objects.filter(anio=anio_actual.year,
                                         empleado__in=Empleados.objects.filter(responsable=empleado))
    for sueldo in sueldos:
        if float(sueldo.total) > sueldo_max:
            sueldo_max = float(sueldo.total)
    return round(sueldo_max, 2)


def calcularSMin(empleado):
    anio_actual = datetime.datetime.now()
    if empleado.resp_depart:
        sueldos = Sueldos.objects.filter(anio=anio_actual.year,
                                         empleado__in=Empleados.objects.filter(area_empleado=empleado.area_empleado))
    else:
        sueldos = Sueldos.objects.filter(anio=anio_actual.year,
                                         empleado__in=Empleados.objects.filter(responsable=empleado))
    sueldo_min = float(sueldos[0].total)
    for sueldo in sueldos:
        if float(sueldo.total) < sueldo_min:
            sueldo_min = float(sueldo.total)
    return round(sueldo_min, 2)


def calcularSMedio(empleado):
    suma_sueldos = 0
    contador = 0
    anio_actual = datetime.datetime.now()
    if empleado.resp_depart:
        sueldos = Sueldos.objects.filter(anio=anio_actual.year,
                                         empleado__in=Empleados.objects.filter(area_empleado=empleado.area_empleado))
    else:
        sueldos = Sueldos.objects.filter(anio=anio_actual.year,
                                         empleado__in=Empleados.objects.filter(responsable=empleado))
    for sueldo in sueldos:
        suma_sueldos += int(sueldo.total)
        contador += 1
    sueldo_medio = suma_sueldos / contador
    return round(sueldo_medio, 2)


def estiloTabla(data, conHeader):
    table_style = []
    if conHeader:
        '''lista_headerTabla = [('BACKGROUND', (0, 0), (-1, 0), colors.white), ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                             ('TOPPADDING', (0, 0), (-1, 0), 10),
                             ('LINEABOVE', (0, 0), (-1, 0), 0.75, '#656d78'),
                             ('LINEBELOW', (0, 0), (-1, 0), 0.75, '#656d78'),
                             ('INNERGRID', (0, 1), (-1, -1), 2, colors.white)
                             ]'''

        lista_headerTabla = [('BACKGROUND', (0, 0), (-1, 0), '#1cace4'), ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                             ('TOPPADDING', (0, 0), (-1, 0), 10),
                             ('GRID', (0, 0), (-1, -1), 2, colors.white)
                             ]

        table_style.extend(lista_headerTabla)

    for i, row in enumerate(data):
        if conHeader and i == 0:
            pass
        else:
            if i % 2 == 0:
                table_style.append(('BACKGROUND', (0, i), (-1, i), '#f0f0f0'))  # tuplas (columna, fila)
                table_style.append(('VALIGN', (0, i), (-1, i), 'TOP'))  # tuplas (columna, fila)
            else:
                table_style.append(('BACKGROUND', (0, i), (-1, i), colors.white))
                table_style.append(('VALIGN', (0, i), (-1, i), 'TOP'))
    return table_style


def aplicarEstiloTextoTabla(columnas,estilo):
    row=[]
    for nombre in columnas:
        row.insert(len(row),Paragraph(nombre, estilo))
    return row


@login_required(login_url='/accounts/login/')
def descarga_evaluacion(request, id_evaluacion, id_empleado):
    user = Empleados.objects.get(email=request.user.username)
    # Indicamos el tipo de contenido a devolver, en este caso un pdf
    response = HttpResponse(content_type='application/pdf')
    buff = BytesIO()

    # TIpo de documento que utilizaremos
    doc = SimpleDocTemplate(buff, pagesize=letter,
                            rightMargin=45, leftMargin=65,
                            topMargin=60, bottomMargin=18, showBoundary=0)


    # Estilos del texto
    estilos = getSampleStyleSheet()

    celeste = '#1cace4'
    grisclaro = '#f0f0f0'
    grisoscuro = '#2b2929'

    ## encabezado
    estilos.add(ParagraphStyle(name='Titulo', alignment=TA_CENTER, fontName='Helvetica-Bold', fontSize=22, leading=22, textColor = celeste))
    estilos.add(ParagraphStyle(name='titulo_gris', alignment=TA_CENTER, fontName='SourceSans', fontSize=12, textColor = grisoscuro))
    estilos.add(ParagraphStyle(name='titulo_anio', alignment=TA_CENTER, fontName='SourceSansBol', fontSize=26, textColor=colors.white))
    ## titulo secciones
    #estilos.add(ParagraphStyle(name='Titulo2', alignment=TA_CENTER, fontName='Helvetica-Bold', fontWeight="bold", fontSize=20))
    estilos.add(ParagraphStyle(name='titulo_seccion', alignment=TA_LEFT, fontName='SourceSans', fontSize=14, textColor=grisoscuro))

    ## tablas
    estilos.add(ParagraphStyle(name='table_header', alignment=TA_CENTER, fontName='SourceSans', fontSize=12, textColor=colors.white))
    estilos.add(ParagraphStyle(name='pregunta', alignment=TA_LEFT, fontName='SourceSans', fontSize=11, leading=15, textColor=grisoscuro))

    ## lista pregunta respuestas
    estilos.add(ParagraphStyle(name='preguntaLista', alignment=TA_LEFT, fontName='SourceSans', fontSize=11, leading=15, backColor=grisclaro,
                               textColor=grisoscuro, spaceAfter = 5))
    estilos.add(ParagraphStyle(name='respuestaLista', alignment=TA_LEFT, fontName='SourceSans', fontSize=10, leading=13,
                               textColor=grisoscuro, spaceAfter = 15, leftIndent = 15))

    ## texto normal
    estilos.add(ParagraphStyle(name='normal', alignment=TA_JUSTIFY, fontName='SourceSans',fontSize=11, leading=15,
                               textColor = '#2b2929'))

    Story = []

    # Logo en encabezado del documento
    logo = './main/static/logo_scalian_indizen.png'
    imagen = Image(logo, 114, 47)

    # Carga de datos de la evaluacion
    empleado = Empleados.objects.get(id_empleado=id_empleado)
    evaluacion = Evaluacion.objects.get(id_evaluacion=id_evaluacion,
                                        empleado=empleado)
    plantilla = PlantillaEvaluacion.objects.get(id_plantilla=evaluacion.id_plantilla.id_plantilla)
    preguntas = Preguntas.objects.filter(id_plantilla=plantilla.id_plantilla)
    todas_respuestas = list()
    for pregunta in preguntas:
        todas_respuestas.append(
            Respuestas.objects.get(id_evaluacion=evaluacion.id_evaluacion, id_pregunta=pregunta.id_pregunta))


    # Escribir datos en el documento
    if evaluacion.responsable == user or user == evaluacion.empleado:
        if request.method == 'GET':
            if plantilla.de_responsable:
                titulo = "EVALUACION AL RESPONSABLE"
            elif plantilla.autoevaluacion:
                titulo = "AUTO EVALUACION DE DESEMPEÑO"
            else:
                titulo = "EVALUACION DE DESEMPEÑO"

            # Datos empleado
            nombre_empleado = "Empleado: " + empleado.nombre + " " + empleado.apellidos
            nombre_responsable = "Responsable: " + evaluacion.responsable.nombre + " " + evaluacion.responsable.apellidos
            fecha_actualizacion = "Fecha última actualización: " + str(evaluacion.updated)
            year_eval = str(evaluacion.anio)

            # Tabla de encabezado
            data=[
                  [imagen,Paragraph(titulo, estilos['Titulo']),Paragraph(year_eval, estilos['titulo_anio'])],
                  ['',Paragraph(nombre_empleado, estilos['titulo_gris']),''],
                  ['',Paragraph(nombre_responsable, estilos['titulo_gris']),''],
                  ['',Paragraph(fecha_actualizacion, estilos['titulo_gris']),'']
            ]
            table = Table(data, colWidths=[120,310,70], rowHeights=(50,15,15,15), style=[
                ('VALIGN', (1, 0), (1, 0), 'TOP'),
                ('BACKGROUND', (2, 0), (2, 2), '#00b0f0'),
                #('TEXTCOLOR', (1, 0), (1, 1), colors.white),
                ('ALIGN', (2, 0), (2, 2), 'CENTER'),
                ('VALIGN', (2, 0), (2, 2), 'CENTER'),
                ('SPAN', (2, 0), (2, 2)),
                ('SPAN', (0, 0),  (0, 2))
            ])

            Story.append(table)
            Story.append(Spacer(1, 50))

            line = HRFlowable(width="100%", thickness=1, lineCap='round', color=grisoscuro, spaceBefore=7, spaceAfter=7,
                       hAlign='LEFT', vAlign='BOTTOM', dash=None)
            #line = HRFlowable(width="10%", thickness=2, lineCap='round', color=celeste, spaceBefore=7, spaceAfter=7,
            #       hAlign = 'CENTER', vAlign = 'BOTTOM', dash = None)
            titulo2 = "PREGUNTAS Y RESPUESTAS"
            Story.append(Paragraph(titulo2, estilos['titulo_seccion']))
            Story.append(line)
            Story.append(Spacer(1, 10))

            ########## SECCIÓN
            # Preguntas y respuestas

            for respuesta in todas_respuestas:
                txt_pregunta = respuesta.id_pregunta.pregunta
                txt_respuesta = respuesta.respuesta
                Story.append(Paragraph(txt_pregunta, estilos['preguntaLista']))
                Story.append(Paragraph(txt_respuesta, estilos['respuestaLista']))


            # Sueldos
            if not plantilla.autoevaluacion and not plantilla.de_responsable:
                fecha = datetime.datetime.now()

                ########## SECCIÓN
                # Tabla sueldo actual
                Story.append(Spacer(1, 40))

                titulo2 = "TABLA SUELDO " + str(fecha.year)
                Story.append(Paragraph(titulo2, estilos['titulo_seccion']))
                Story.append(line)
                Story.append(Spacer(1, 10))

                sueldos = Sueldos.objects.filter(empleado=empleado, anio=fecha.year)
                data = []
                data.append(aplicarEstiloTextoTabla(['AÑO', 'RF', 'VI', 'VE', 'BS', 'BS', 'KM', 'GUARDIAS', 'TOTAL'], estilos['table_header']))
                datos_sueldo = list()
                for sueldo in sueldos:
                    datos_sueldo.append(sueldo.anio)
                    datos_sueldo.append(sueldo.retribucion_fija)
                    datos_sueldo.append(sueldo.varibale_individual)
                    datos_sueldo.append(sueldo.varibale_empresa)
                    datos_sueldo.append(sueldo.beneficios_sociales)
                    datos_sueldo.append(sueldo.bonus_dietas)
                    datos_sueldo.append(sueldo.kilometros)
                    datos_sueldo.append(sueldo.guardias)
                    datos_sueldo.append(sueldo.total)

                    data.append(aplicarEstiloTextoTabla(datos_sueldo,estilos['normal']))
                    datos_sueldo = list()

                table = Table(data)
                table_style = estiloTabla(data, True)
                table.setStyle(TableStyle(table_style))
                Story.append(table)

                ########## SECCIÓN
                # Tabla sueldo anterior

                Story.append(Spacer(1, 30))
                titulo2 = "TABLA SUELDOS ANTERIORES"

                Story.append(Paragraph(titulo2, estilos['titulo_seccion']))
                Story.append(line)
                Story.append(Spacer(1, 10))

                sueldos = Sueldos.objects.filter(empleado=empleado)
                data = []
                data.append(aplicarEstiloTextoTabla(['AÑO', 'RF', 'VI', 'VE', 'BS', 'BS', 'KM', 'GUARDIAS', 'TOTAL'], estilos['table_header']))
                datos_sueldo = list()
                for sueldo in sueldos:
                    datos_sueldo.append(sueldo.anio)
                    datos_sueldo.append(sueldo.retribucion_fija)
                    datos_sueldo.append(sueldo.varibale_individual)
                    datos_sueldo.append(sueldo.varibale_empresa)
                    datos_sueldo.append(sueldo.beneficios_sociales)
                    datos_sueldo.append(sueldo.bonus_dietas)
                    datos_sueldo.append(sueldo.kilometros)
                    datos_sueldo.append(sueldo.guardias)
                    datos_sueldo.append(sueldo.total)

                    data.append(aplicarEstiloTextoTabla(datos_sueldo, estilos['normal']))
                    datos_sueldo = list()

                table = Table(data)
                table_style = estiloTabla(data, True)
                table.setStyle(TableStyle(table_style))
                Story.append(table)

            doc.build(Story)
            if plantilla.autoevaluacion:
                response[
                    'Content-Disposition'] = 'attachment; filename=' + "auto_evaluacion_" + empleado.nombre + "_" + empleado.apellidos + ".pdf"
            else:
                response[
                    'Content-Disposition'] = 'attachment; filename=' + "evaluacion_" + empleado.nombre + "_" + empleado.apellidos + ".pdf"
            response.write(buff.getvalue())
            buff.close()
            return response
    else:
        return '404.html'


def comprobar_empleado(correo):
    try:
        if Empleados.objects.get(email=correo):
            return False
        else:
            return True
    except:
        return True


def randomStringDigits(stringLength=9):
    """Generate a random string of letters and digits """
    lettersAndDigits = string.ascii_letters + string.digits
    return ''.join(random.choice(lettersAndDigits) for i in range(stringLength))


def crear_usuario(empleado):
    try:
        # Dar de alta al usuario
        usuario = User.objects.create_user(
            username=empleado.email,
            email=empleado.email,
            password=empleado.contrasenia,
        )
        usuario.first_name = empleado.nombre
        usuario.last_name = empleado.apellidos
        # Asignar grupo
        if empleado.evaluador:
            usuario.groups.add(Group.objects.get(name='responsable'))
            usuario.groups.add(Group.objects.get(name='empleado'))
        else:
            usuario.groups.add(Group.objects.get(name='empleado'))

        if empleado.resp_depart:
            usuario.groups.add(Group.objects.get(name='responsable'))

        usuario.save()
        return True
    except:
        return False


def comprobar_usuario(request, id_empleado):
    try:
        empleado = Empleados.objects.get(id_empleado=id_empleado)
        grupos = request.user.groups.values_list('name', flat=True)
        result = False
        if not "admin" in grupos:
            responsable_depart = Empleados.objects.get(email=request.user)
        if "admin" in grupos:
            result = True
        elif responsable_depart.resp_depart and responsable_depart.area_empleado == empleado.area_empleado:
            result = True
        else:
            for grupo in grupos:
                if grupo == 'admin':
                    result = True
                    break
                elif grupo == 'empleado':
                    if request.user.username == empleado.email:
                        result = True
                        break
                elif grupo == 'responsable':
                    if request.user.username == empleado.email:
                        result = True
                        break
                else:
                    result = False

        return result
    except:
        return False


def comprobar_responsable(request, id_evaluacion):
    try:
        evaluacion = Evaluacion.objects.get(id_evaluacion=id_evaluacion)
        grupos = request.user.groups.values_list('name', flat=True)
        request_user = Empleados.objects.get(email=request.user.username)
        result = False

        if evaluacion.id_plantilla.de_responsable:
            return False

        if request_user.resp_depart and request_user.area_empleado == evaluacion.empleado.area_empleado:
            result = True
        else:
            for grupo in grupos:
                if grupo == 'admin':
                    result = True
                    break
                elif grupo == 'responsable':
                    if request.user.username == evaluacion.responsable.email:
                        result = True
                    break
                else:
                    result = False

        return result
    except:
        if request.user.username == 'admin':
            return True
        else:
            return False


def comprobar_resp_depart(request, id_empleado):
    empleado = Empleados.objects.get(id_empleado=id_empleado)
    grupos = request.user.groups.values_list('name', flat=True)
    if not "admin" in grupos:
        request_user = Empleados.objects.get(email=request.user)
    if "admin" in grupos:
        return True
    if request_user.resp_depart and request_user.area_empleado == empleado.area_empleado:
        return True
    else:
        return False


def comprobar_identificador(request, id):
    if request.user.username == ADMIN_USER_NAME:
        return True

    success = False
    try:
        # comprobamos si el identificador que llega tiene como responsable asociado el usuario que esta logado en este momento
        empleado = Empleados.objects.get(identificador=id)
        if empleado and request.user.username == empleado.responsable.email:
            success = True
    except Exception as e:
        logger.error('[comprobar_identificador] identificador[%s] no esta asociado al responsable [%s]' % (
            id, request.user.username))
    return success


def comprobar_identificador_ep(request, id):
    if request.user.username == ADMIN_USER_NAME:
        return True

    success = False
    try:
        # comprobamos que el identificador es de un empleado cuya evaluacion tiene como responsable el usuario de la request
        responsable_logado = Empleados.objects.get(email=request.user.username)
        empleado = Empleados.objects.get(identificador=id)
        count_evaluaciones_del_responsable_logado = Evaluacion.objects.filter(
            responsable=responsable_logado.id_empleado, empleado=empleado).count()
        if count_evaluaciones_del_responsable_logado > 0 and request.user.username == empleado.responsable.email:
            success = True
    except Exception as e:
        logger.error('[comprobar_identificador] identificador[%s] no esta asociado al responsable [%s] [%s]' % (
            id, request.user.username, e))
    return success


def comprobar_sueldo(request):
    try:
        result = False
        grupos = request.user.groups.values_list('name', flat=True)
        for grupo in grupos:
            if grupo == 'ver_sueldos':
                result = True
                break
            else:
                result = False
        return result
    except:
        return False


def comprobar_verificacion(id_evaluacion):
    evaluacion = Evaluacion.objects.get(id_evaluacion=id_evaluacion)
    if evaluacion.verificado:
        return True
    else:
        return False


def devolver_dependientes(respon):

    if respon.id_empleado == respon.responsable.id_empleado:
        #print('CEO')
        #Estamos en el caso del CEO
        empleados = Empleados.objects.filter(responsable=respon).exclude(id_empleado__exact=respon.id_empleado)
    
    else:
        #print('Otro caso')
        empleados = Empleados.objects.filter(responsable=respon, area_empleado=respon.area_empleado)
    
    lista_empleados = list(empleados) 

    """ if not responsable.responsable:
            empleados = Empleados.objects.filter(responsable=responsable)
        else:
            empleados = Empleados.objects.filter(responsable=responsable, area_empleado=responsable.area_empleado)
        lista_empleados = list(empleados) """
    return lista_empleados


def insert_new_level(empleados, organigrama):
    
    for empleado in empleados:
        try:
            evaluaciones = Evaluacion.objects.filter(responsable=empleado)
        except:
            evaluaciones = ""

        if evaluaciones:
            #print('Encuentra evaluaciones')
            dato_empleado = '* ' + empleado.nombre + ' ' + empleado.apellidos + ' | ' + empleado.rol + ' | ' + empleado.area_empleado
        else:
            #print('No Encuentra evaluaciones')
            dato_empleado = empleado.nombre + ' ' + empleado.apellidos + ' | ' + empleado.rol + ' | ' + empleado.area_empleado

        organigrama[dato_empleado] = {}
        dependientes = devolver_dependientes(empleado)
      
        if dependientes is not None:
            insert_new_level(dependientes, organigrama[dato_empleado])
        
    return organigrama


def crearListaOrganigrama(diccionario, lista_datos, espacio=0):
    #print('__________*************',diccionario)
    for h, k in diccionario.items():
        lista_datos.append('\t' * espacio + h)
        if type(k) is not None:
            crearListaOrganigrama(diccionario[h], lista_datos, espacio + 2)

    return lista_datos


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


def chartEmpleado(id_empleado):
    # Se pasan los datos mediante dic

    dataSource = {}
    dataSource['chart'] = {
        "caption": "Progreso Sueldo",
        "captionFont": "Arial",
        "captionFontSize": "18",
        "captionFontColor": "#656160",
        "captionFontBold": "1",
        "yAxisName": "Sueldo del empleado",
        "anchorradius": "5",
        "plotToolText": "Sueldo en $label es <b>$dataValue</b> <br> $displayValue",
        "toolTipBgColor": "#efefef",
        "showHoverEffect": "5",
        "showvalues": "0",
        "numberSuffix": "€",
        "setadaptiveymin": "1000",
        "theme": "fusion",
        "canvasbgColor": "#1790e1",
        "canvasbgAlpha": "20",
        #"bgColor": "#efefef",
        "anchorBgColor": "#1cace4",
        "paletteColors": "#1cace4"
    }

    # Los datos se recogen en JSON.

    dataSource['data'] = []

    for empDatos in Sueldos.objects.filter(empleado=Empleados.objects.get(id_empleado=id_empleado)).order_by('anio'):
        data = dict()
        data['label'] = empDatos.anio
        data['value'] = empDatos.total
        data[
            'displayValue'] = "Fija: " + (intcomma(empDatos.retribucion_fija)) + "<br>VD: " + (intcomma(empDatos.varibale_individual))\
                              + "<br> VE: " + (intcomma(empDatos.varibale_empresa)) + "<br>BS: " + \
                              (intcomma(empDatos.beneficios_sociales)) + "<br>Dietas: " + \
                              (intcomma(empDatos.bonus_dietas)) + "<br>KM: " + (intcomma(empDatos.kilometros))\
                              + "<br> Guardias: " + (intcomma(empDatos.guardias)) + \
                              "<br>Total: " + (intcomma(empDatos.total))
        dataSource['data'].append(data)

    # Crear el objeto
    spline = FusionCharts("line", str(id_empleado), '100%', '400', "chart-1", "json", dataSource)
    return spline.render()


def chartResponsable(empleados, tipoSueldo, years):
    anio_actual = datetime.datetime.now()

    dataSource = {}
    dataSource['chart'] = {
        "caption": "Sueldos empleados",
        "captionFont": "Arial",
        "captionFontSize": "18",
        "captionFontColor": "#656160",
        "captionFontBold": "1",
        "usePlotGradientColor": "1",
        "plotGradientColor": "#1cace4",
        "plotFillRatio": "20,60",
        "numbersuffix": "€",
        "scrollheight": "10",
        "numvisibleplot": "10",
        "showanchors": "6",
        'labeldisplay': "auto",
        "theme": "fusion"
    }

    # CATEGORY
    dataSource['categories'] = list()
    dict_category = dict()
    dict_category['category'] = list()
    for empDatos in empleados:
        datos = dict()
        datos['label'] = empDatos.nombre + " " + empDatos.apellidos
        dict_category['category'].append(datos)

    dataSource['categories'].append(dict_category)

    # DATASET
    # Data de las barras
    dataSource['dataset'] = list()
    dict_data = dict()
    dict_data['data'] = list()
    if years and tipoSueldo:
        for year in years:
            for empDatos in empleados:
                datos = dict()
                try:
                    sueldo = Sueldos.objects.get(anio=year, empleado=empDatos)

                    if tipoSueldo[0] == '1':
                        datos['value'] = sueldo.total
                        dict_data['seriesname'] = "Sueldo total " + str(year)

                    else:
                        datos['value'] = ((sueldo.retribucion_fija))
                        dict_data['seriesname'] = "Sueldo RF " + str(year)
                except:
                    datos['value'] = 0
                dict_data['data'].append(datos)

            dataSource['dataset'].append(dict_data)
            dict_data = dict()
            dict_data['data'] = list()

    # Necesario para el GET
    else:
        dict_data = dict()
        dict_data['seriesname'] = "Sueldo total " + str(anio_actual.year)
        dict_data['data'] = list()

        for empDatos in empleados:
            datos = dict()
            try:
                sueldo = Sueldos.objects.get(empleado=empDatos, anio=anio_actual.year)

                datos['value'] = ((sueldo.total))
            except:
                datos['value'] = 0
            dict_data['data'].append(datos)

        dataSource['dataset'].append(dict_data)

    # DATASET2
    # Data de la linea
    dict_data = dict()
    dict_data['seriesname'] = "Media sueldo"
    dict_data['renderas'] = "line"
    dict_data['data'] = list()
    datos = dict()

    recorrer = len(empleados)
    while recorrer != 0:
        try:
            if tipoSueldo[0] == '2':
                datos['value'] = 1100
            else:
                datos['value'] = 16000
        except:
            datos['value'] = 16000
        dict_data['data'].append(datos)

        recorrer -= 1

    dataSource['dataset'].append(dict_data)

    chart = FusionCharts('scrollcombi2d', 'ex1', '100%', '400', 'chart-1', 'json', dataSource)
    return chart.render()


def chartResponsable_propuesto(empleados, tipoSueldo):

    dataSource = {}
    dataSource['chart'] = {
        "caption": "Sueldos propuestos empleados",
        "captionFont": "Arial",
        "captionFontSize": "18",
        "captionFontColor": "#656160",
        "captionFontBold": "1",
        "usePlotGradientColor": "1",
        "plotGradientColor": "#1cace4",
        "plotFillRatio": "20,60",
        "numbersuffix": "€",
        "scrollheight": "10",
        "numvisibleplot": "10",
        "showanchors": "6",
        'labeldisplay': "auto",
        "theme": "fusion"
    }

    # CATEGORY
    dataSource['categories'] = list()
    dict_category = dict()
    dict_category['category'] = list()
    for empDatos in empleados:
        datos = dict()
        datos['label'] = empDatos.nombre + " " + empDatos.apellidos
        dict_category['category'].append(datos)

    dataSource['categories'].append(dict_category)

    # DATASET
    # Data de las barras
    dataSource['dataset'] = list()
    dict_data = dict()
    dict_data['data'] = list()
    if tipoSueldo:
        for empDatos in empleados:
            datos = dict()
            try:
                sueldo = Sueldos_propuestos.objects.get(empleado=empDatos)

                if tipoSueldo[0] == '1':
                    datos['value'] = sueldo.total
                    dict_data['seriesname'] = "Sueldo total "

                else:
                    datos['value'] = sueldo.retribucion_fija
                    dict_data['seriesname'] = "Sueldo RF "
            except:
                datos['value'] = 0
            dict_data['data'].append(datos)

        dataSource['dataset'].append(dict_data)
        dict_data = dict()
        dict_data['data'] = list()
    # Necesario para el GET
    else:
        dict_data = dict()
        dict_data['seriesname'] = "Sueldo total "
        dict_data['data'] = list()

        for empDatos in empleados:
            datos = dict()
            try:
                sueldo = Sueldos_propuestos.objects.get(empleado=empDatos)

                datos['value'] = sueldo.total
            except:
                datos['value'] = 0
            dict_data['data'].append(datos)

        dataSource['dataset'].append(dict_data)

    chart = FusionCharts('scrollcombi2d', 'ex1', '100%', '400', 'chart-1', 'json', dataSource)
    return chart.render()


def chart_eval_responsable(responsable):

    dataSource = {}
    dataSource['chart']={
        "caption": "Notas como responsable",
        "captionFont": "Arial",
        "captionFontSize": "18",
        "captionFontColor": "#656160",
        "captionFontBold": "1",
        "xAxisName": "Preguntas",
        "yAxismaxvalue": "5",
        "yAxisName": "Valoraciones recibidas",
        "outCnvBaseFontColor": "#656160",
        "showvalues": "1",
        "showlabels": "1",
        "valueFont":"Arial",
        "valueFontColor":"#1cace4",
        "valueFontBold":"1",
        #"showpercentintooltip": "0",
        "numberprefix": "",
        "usePlotGradientColor": "1",
        "plotGradientColor": "#1cace4",
        "plotFillRatio": "20,60",
        #"enablemultislicing": "1",
        "theme": "fusion"
    }
    #Año actual
    fecha = datetime.datetime.now()

    plantillas = PlantillaEvaluacion.objects.filter(de_responsable=True)
    evaluaciones = Evaluacion.objects.filter(id_plantilla__in=plantillas, responsable=responsable, anio=fecha.year)
    print('Las evaluaciones son:', evaluaciones)
    respuestas = Respuestas.objects.filter(id_evaluacion__in=evaluaciones)
    print('Las respuestas son:', respuestas)
    

    notas_preguntas = dict()
    
    for respuesta in respuestas:
        notas_preguntas[respuesta.id_pregunta.pregunta] = list()

    for respuesta in respuestas:
        notas_preguntas[respuesta.id_pregunta.pregunta].append(respuesta.respuesta)
    
    print('El diccionario con las preguntas y sus respuestas es', notas_preguntas)

    dataSource['data'] = list()

    '''for notas in notas_preguntas:
        for nota in notas_preguntas[notas]:
            suma_notas += int(nota)
        media_notas = suma_notas / len(notas_preguntas[notas])
        datos = dict()
        datos['label'] = notas
        datos['value'] = media_notas
        dataSource['data'].append(datos)
    '''
    
    for notas in notas_preguntas:
        suma_notas = 0
        total_respuestas_validas=len(notas_preguntas[notas])
        for nota in notas_preguntas[notas]:
            try:
                nota = int(nota)
                suma_notas += int(nota)
            except ValueError:
                #Las respuestas no válidas no perjudican a la media
                total_respuestas_validas -= 1
                pass 
  
        if suma_notas !=0:
            media_notas = suma_notas / total_respuestas_validas
            datos = dict()
            datos['label'] = notas
            datos['value'] = media_notas
            dataSource['data'].append(datos)

    chart = FusionCharts('column2d', 'chartNota', '100%', '400', 'chart-2', 'json', dataSource)
   #chart = FusionCharts('pie3d', 'chartNota', '100%', '100%', 'chart-2', 'json', dataSource)

    return chart.render()
