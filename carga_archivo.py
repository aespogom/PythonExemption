import csv
import io
import logging

from main.models import Empleados
from main.utilities.models_carga_empelado import empleadoObj, evaluacionObj, sueldoObj, preguntaObj, respuestaObj

logger = logging.getLogger(__name__)

archivoCorrecto = False


def insertarEmpleado(datos_empleado):

    # identificador, email, nombre, apellidos, f_antiguedad, area, rol, evaluador, responsable_identificador, resp_depart
    nuevo_empleado = empleadoObj(datos_empleado[0], datos_empleado[1], datos_empleado[2], datos_empleado[3],
                                 datos_empleado[4], datos_empleado[5], datos_empleado[6], datos_empleado[7],
                                 datos_empleado[8], datos_empleado[9], datos_empleado[10])
    insertado = nuevo_empleado.insertarEmpleado()
    return insertado

def insertarSueldos(datos_sueldos):

    #año, rf, vi, ve, bs, b/d, kms, guardias, tipo, total, incremento, id_empleado
    nuevo_sueldo = sueldoObj(datos_sueldos[0], datos_sueldos[1], datos_sueldos[2], datos_sueldos[3],
                             datos_sueldos[4], datos_sueldos[5], datos_sueldos[6], datos_sueldos[7],
                             datos_sueldos[8], datos_sueldos[9], datos_sueldos[10], datos_sueldos[11])
    insertado = nuevo_sueldo.insertarSueldo()
    return insertado


def insertarEvaluacion(datos_evaluacion):
    #'plantilla', 'anio', 'detalle', 'responsable_identificador', 'empleado_identificador', 'verificado', 'fecha_verificado', 'observaciones', 'externo'
    nueva_evaluacion = evaluacionObj(datos_evaluacion[0], datos_evaluacion[1], datos_evaluacion[2], datos_evaluacion[3],
                                     datos_evaluacion[4], datos_evaluacion[5], datos_evaluacion[6], datos_evaluacion[7],
                                     datos_evaluacion[8])

    insertado = nueva_evaluacion.insertarEvaluacion()
    return insertado


def insertarPregunta(datos_pregunta):
    #'id_plantilla', 'id_seccion', 'pregunta'
    nueva_pregunta = preguntaObj(datos_pregunta[0], datos_pregunta[1], datos_pregunta[2])

    insertado = nueva_pregunta.insertarPregunta()
    return insertado


def insertarRespuesta(datos_respuesta):
    #'id_evaluacion', 'id_pregunta', 'respuesta'
    nueva_respuesta = respuestaObj(datos_respuesta[0], datos_respuesta[1], datos_respuesta[2])

    insertado = nueva_respuesta.insertarRespuesta()
    return insertado


def comprobarEmpleado(email):
    try:
        if Empleados.objects.get(email=email):
            return False
    except:
        return True


def processFileEmpleados(csv_file):
    logger.debug('/processFile/')
    #data.fieldnames = 'identificador', 'email', 'nombre', 'apellidos', 'f_antiguedad', 'area_empleado', 'rol', 'evaluador', 'responsable_identificador', 'resp_depart', 'ver_sueldos'
    data = csv_file.read().decode('utf-8')
    io_string = io.StringIO(data)
    next(io_string)
    try:
        for d in csv.reader(io_string, delimiter=',', quotechar='|'): #fila
            #comprobar que no existe ya el empleado, email es un campo unico siempre
            if comprobarEmpleado(d[1]):
                try:
                    if insertarEmpleado(d):
                        logger.debug("Empleado creado: " + d[2] + ' ' + d[3])
                except Exception as ex:
                    logger.error('Error al en el insert de empleado', ex)

        return True
    except Exception as ex:
        logger.error('Error al procesar el empleado', ex)


def processFileSueldos(csv_file):
    logger.debug('/processFile/')
    data = csv_file.read().decode('utf-8')
    io_string = io.StringIO(data)
    next(io_string)
    #data.fieldnames = 'id_empleado','rf', 'vi', 've', 'bs', 'bd', 'kms', 'guardias', 'tipo', 'total', 'incremento', 'anio'
    #data.__next__()
    try:
        for d in csv.reader(io_string, delimiter=',', quotechar='|'): #fila
            empleado = Empleados.objects.filter(id_empleado=d[0])
            if empleado:
                insertarSueldos(d)
                logger.error("Sueldo creado: " + d[9] + ' ' + d[0])
            else:
                logger.error('Empleado no existe')

        return True
    except Exception as ex:
        logger.error('Error al procesar el sueldo', ex)


def processFileEvaluacion(csv_file):
    logger.debug('/processFile/')
    data = csv_file.read().decode('utf-8')
    io_string = io.StringIO(data)
    next(io_string)
    #data.fieldnames = 'plantilla', 'anio', 'detalle', 'responsable_identificador', 'empleado_identificador', 'verificado', 'fecha_verificado', 'observaciones', 'externo'
    #3 ultimas no son obligatorias
    try:
        for d in csv.reader(io_string, delimiter=',', quotechar='|'): #fila
            insertarEvaluacion(d)
            logger.debug('cargando eval')
            logger.error("Evaluacion creada: " + d[1] + ' ' + d[4])
        return True
    except Exception as ex:
        logger.error('Error al procesar la evaluacion', ex)
        logger.debug('error')


def processFilePreguntas(csv_file):
    logger.debug('/processFile/')
    data = csv_file.read().decode('utf-8')
    io_string = io.StringIO(data)
    next(io_string)
    #data.fieldnames = 'id_plantilla', 'id_seccion', 'pregunta'
    try:
        for d in csv.reader(io_string, delimiter=',', quotechar='|'): #fila
            insertarPregunta(d)
            logger.debug('cargando pregunta')
            logger.error("Pregunta creada: " + d[1] + ' ' + d[2])
        return True
    except Exception as ex:
        logger.error('Error al procesar la pregunta', ex)
        logger.debug('error')


def processFileRespuestas(csv_file):
    logger.debug('/processFile/')
    data = csv_file.read().decode('utf-8')
    io_string = io.StringIO(data)
    next(io_string)
    #data.fieldnames = 'id_evaluacion', 'id_pregunta', 'respuesta'
    try:
        for d in csv.reader(io_string, delimiter=',', quotechar='|'): #fila
            insertarRespuesta(d)
            logger.debug('cargando respuesta')
            logger.error("Respuesta creada: " + d[1] + ' ' + d[2])
        return True
    except Exception as ex:
        logger.error('Error al procesar la respuesta', ex)
        logger.debug('error')
