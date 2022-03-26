import logging
import json
import os
import shutil
import tarfile
from datetime import datetime
import base64
import zipfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.db.models import Q
from django_tables2 import RequestConfig
from django_tables2.export.export import TableExport
from juridico_app.tables.table import RegistroOperacionesTable
from juridico_app.utilities.s3_utilities import descargar_carpeta_s3, descargar_s3, subir_s3, \
    listar_carpeta_s3_post_documentacion, borrar_s3, listar_carpeta_s3_post, listar_carpeta_s3_ayuda, \
    initiate_glacier_restore, check_glacier_restoration
from juridico_app.utilities.utilities import get_folders, get_folder_data, get_folders_SERIE_RAMA_FECHA, \
    get_folders_EQUIPO_MOTRIZ, get_archivos, descargar_zip, \
    foldersToTable, find_path_archivo, get_contenido_carpeta, form_generator, registro_operaciones_filtro, \
    get_object_from_filename, descargar_csv, limpiar_static, comprobar_extensiones, get_folders_SC, \
    get_contenido_carpeta_SC, descargar_zip_SC, borrar_s3_utilities
from juridico_app.utilities.log_access import log_access
from juridico_app.models import Usuarios, GestionLogin, JuridicoRegistroOperaciones, Empresas
from juridico_app.decorators import allowed_users, valid_token
from juridico_app.utilities.constants import ALSTOM_EMPRESA_ID, INDIZEN_EMPRESA_ID, EQUIPOS, MOTRIZ, OPERACIONES
from alstom_juridico.settings import config, STATIC_DIR, STATIC_DESCARGAS_ROOT, BUCKETS, STATIC_SUBIDAS_ROOT, \
    STATIC_DESCARGAS_URL

logger = logging.getLogger(__name__)

@valid_token
def inicio(request):
    log_access(request)
    logger.debug('[juridico_views.py][juridico_inicio_ope]')

    context = {}

    id_empresa = request.user.id_empresa.id_empresa
    context['empresa'] = Empresas.objects.filter(id_empresa=id_empresa).values('nombre_empresa')[0]
    context['folders'] = get_folders_SERIE_RAMA_FECHA(id_empresa, request.user.tipo == 'CL')
    context['folders2'] = [] #hasta que no se seleccione serie,rama,anio,mes y dia no aparece el segundo arbol
    context['folder_data'] = [] #hasta que no se seleccione serie,rama,anio,mes y dia no aparecen archivos
    context['path'] = []
    context['equipos_juridico'] = EQUIPOS
    context['motrices_juridico'] = MOTRIZ

    context['permiso_subir'] = False
    context['permiso_eliminar'] = False
    #permisos acciones segun usuario
    if request.user.tipo == 'OP' or request.user.tipo == 'EN':
        context['permiso_subir'] = True

    elif request.user.tipo == 'AD':
        context['permiso_subir'] = True
        context['permiso_eliminar'] = True

    #Tree EQUIPO-MOTRIZ y archivos de forma dinamica a partir del tree SERIE-RAMA-FECHA
    if request.is_ajax() and ('serie' in request.GET or 'rama' in request.GET or 'anio' in request.GET or 'mes' in request.GET or 'dia' in request.GET):

        serie = context['folders']['data'][int(request.GET['serie'])]['text']
        items_in_serie = context['folders']['data'][int(request.GET['serie'])]['items']
        folders2 = {}
        folderData = {}
        folderDatalist = []
        path = serie

        if (request.GET['rama']) != "" and serie != 'S-C':
            rama = items_in_serie[int(request.GET['rama'])]['text']
            items_in_ramas = items_in_serie[int(request.GET['rama'])]['items']
            path = path + '/' + rama

            if (request.GET['anio']) != "":
                anio = items_in_ramas[int(request.GET['anio'])]['text']
                items_in_anio = items_in_ramas[int(request.GET['anio'])]['items']
                path = path + '/' + anio

                if (request.GET['mes']) != "":
                    mes = items_in_anio[int(request.GET['mes'])]['text']
                    items_in_mes = items_in_anio[int(request.GET['mes'])]['items']
                    path = path + '/' + mes

                    if (request.GET['dia']) != "":
                        dia = items_in_mes[int(request.GET['dia'])]['text']
                        path = path + '/' + dia
                        folders2, folderData, path = get_folders_EQUIPO_MOTRIZ(path)
                        folderDatalist = foldersToTable(folderData, path)
        elif serie == 'S-C':
            if (request.GET['rama']) != "":
                anio = items_in_serie[int(request.GET['rama'])]['text']
                items_in_anio = items_in_serie[int(request.GET['rama'])]['items']
                path = path + '/' + anio

                if (request.GET['anio']) != "":
                    mes = items_in_anio[int(request.GET['anio'])]['text']
                    items_in_mes = items_in_anio[int(request.GET['anio'])]['items']
                    path = path + '/' + mes

                    if (request.GET['mes']) != "":
                        dia = items_in_mes[int(request.GET['mes'])]['text']
                        path = path + '/' + dia
                        folders2, folderData, path = get_folders_EQUIPO_MOTRIZ(path)
                        folderDatalist = foldersToTable(folderData, path)

        # Cuando se pasa a true es que hay archivos en glacier y no se debe dejar descargar lo de un día
        block_dia_glacier = False
        if any(['glacier_' in el.get('text') for el in folderData]) and 'dia' in request.GET:
            block_dia_glacier = True

        return HttpResponse(json.dumps({'folders2': folders2, 'folderData': folderDatalist, 'path': path, 'block_dia': block_dia_glacier}),
                            content_type="application/json")

    if request.is_ajax() and ('equipo' in request.GET or 'localizacion' in request.GET or 'path' in request.GET):

        folderData, path = get_archivos(request.GET['path'], request.GET['equipo'], request.GET['localizacion'])
        folderDatalist = foldersToTable(folderData, path)

        # Cuando se pasa a true es que hay archivos en glacier y no se debe dejar descargar lo de un día
        block_dia_glacier = False
        if any(['glacier_' in el.get('text') for el in folderData]):
            block_dia_glacier = True

        return HttpResponse(json.dumps({'folderData': folderDatalist, 'path': path, 'block_dia': block_dia_glacier}), content_type="application/json")

    if request.is_ajax() and ('descarga_todo' in request.GET):

        carpeta = request.GET['descarga_todo']

        #listamos toodo lo que hay dentro del folder, result es un diccionario con serie,rama,etc para cada fichero
        if 'S-C' not in carpeta:
            archivos = get_contenido_carpeta(carpeta)
            # descargamos y montamos el zip
            confirmacion, url, nombre_zip = descargar_zip(archivos, carpeta, request.GET['tk'])
        else:
            archivos = get_contenido_carpeta_SC(carpeta)
            confirmacion, url, nombre_zip = descargar_zip_SC(archivos, carpeta, request.GET['tk'])


        if confirmacion:

            JuridicoRegistroOperaciones.objects.create(usuario=request.user.username,
                                                       fichero=carpeta,
                                                       operacion=OPERACIONES['Descargar'],
                                                       resultado_operacion='Success')

        else:

            JuridicoRegistroOperaciones.objects.create(usuario=request.user.username,
                                                       fichero=carpeta,
                                                       operacion=OPERACIONES['Descargar'],
                                                       resultado_operacion='Fail')

        return HttpResponse(json.dumps({'zip_estado': confirmacion, 'url_zip': url, 'filename': nombre_zip}), content_type="application/json")

    if request.is_ajax() and 'borrar_subida' in request.GET:
        token = request.GET['tk']
        path = os.path.join(STATIC_SUBIDAS_ROOT, token)
        if os.path.exists(path):
            for f in os.listdir(path):
                os.remove(os.path.join(path,f))

        return HttpResponse(json.dumps('Success'), content_type="application/json")

    if request.is_ajax() and 'file_upload' in request.POST:

        try:
            data_str = request.POST['file_upload']
            filename = request.POST['file_name']
            # por si existe un espacio en el nombre del comprimido --> lo quitamos
            filename = filename.replace(' ', '')
            data = data_str[data_str.find(',')+1:]
            data_bytes = str.encode(data)

            path_zip = os.path.join(STATIC_SUBIDAS_ROOT, request.GET['tk'], filename)

            with open(path_zip, "wb") as fh:
                fh.write(base64.decodebytes(data_bytes))

            if path_zip.endswith('.zip'):
                zip = zipfile.ZipFile(path_zip)
                comprimido_list_files = zip.namelist()
                extensionOK, sufijoOK, errores = comprobar_extensiones(filename, comprimido_list_files)
                zip.close()

            elif path_zip.endswith('tar.gz'):
                tar = tarfile.open(path_zip, "r")
                comprimido_list_files = []
                for name in tar.getnames():
                    name = name.replace('down//','')
                    name = name.replace('SIEMENS/', '')
                    comprimido_list_files = [name]
                extensionOK, sufijoOK, errores = comprobar_extensiones(filename, comprimido_list_files)
                tar.close()

            else:
                errores = tuple(['\nLa carpeta no está comprimida correctamente \nNombre carpeta comprimida: {} '
                                     '\nCompresiones correctas: tar.gz o zip'.format(filename)])
                extensionOK = False
                sufijoOK = False

            if extensionOK == True and sufijoOK == True:
                return HttpResponse(json.dumps('Success'), content_type="application/json")

            else:
                os.remove(path_zip)
                return HttpResponse(json.dumps({'Fail': errores}), content_type="application/json")

        except Exception as e:
            print(e)
            return HttpResponse(json.dumps('Fail'), content_type="application/json")

    if request.is_ajax() and 'list_files_to_s3' in request.GET:

        list_files_dragdrop = request.GET['list_files_to_s3'].split(';')
        path = os.path.join(STATIC_SUBIDAS_ROOT, request.GET['tk'])

        for file in list_files_dragdrop:
            # por si existe un espacio en el nombre del comprimido --> lo quitamos xq ya se ha guardado sin espacios en static
            file = file.replace(' ', '')

            object_file = get_object_from_filename(file)

            s3_path = object_file['serie'] +'/'+ object_file['rama'] +'/'+ object_file['year'] +'/'+\
                      object_file['month'] +'/'+ object_file['day'] + '/' + object_file['equipo'] +'/'+\
                      object_file['motriz'] +'/'+file

            print(s3_path)

            response = subir_s3(path, file, s3_path, BUCKETS['juridico'])

            JuridicoRegistroOperaciones.objects.create(usuario=request.user.email,
                                                       fichero=file,
                                                       operacion=OPERACIONES['Subir'],
                                                       resultado_operacion=response['result'])

        return HttpResponse(json.dumps(response), content_type="application/json")

    if request.is_ajax() and 'descarga_archivo_filename' in request.GET:

        path = request.GET['descarga_archivo_path']
        filename = request.GET['descarga_archivo_filename']

        full_path = find_path_archivo(path,filename)

        if 'glacier_' not in full_path:

            descargar_s3(os.path.join(STATIC_DESCARGAS_ROOT, request.GET['tk']),
                         full_path,
                         filename,
                         BUCKETS['juridico'])

            path_localfile = os.path.join(STATIC_DESCARGAS_ROOT, request.GET['tk'], filename)
            rel_path = STATIC_DESCARGAS_URL + '/' + request.GET['tk'] + '/' + filename
            #rel_path = os.path.join(STATIC_DESCARGAS_URL, request.GET['tk'] , filename)

            if os.path.exists(path_localfile):

                # Descarga exitosa
                JuridicoRegistroOperaciones.objects.create(usuario=request.user.username,
                                                           fichero=filename,
                                                           operacion=OPERACIONES['Descargar'],
                                                           resultado_operacion='Success')

                return HttpResponse(json.dumps({'file_estado': True, 'url_file': rel_path, 'filename': filename}),
                                    content_type="application/json")

            # Fallo en la descarga
            JuridicoRegistroOperaciones.objects.create(usuario=request.user.username,
                                                       fichero=filename,
                                                       operacion=OPERACIONES['Descargar'],
                                                       resultado_operacion='Fail')

            return HttpResponse(json.dumps({'file_estado': False, 'url_file': None}),
                                content_type="application/json")

        else:

            restore_status = check_glacier_restoration(BUCKETS['juridico'], full_path)

            if restore_status == 'null':
                response = initiate_glacier_restore(request.user.email, BUCKETS['juridico'], full_path)

                resultado = "Success" if (response == 200 or response == 202) else "Fail"

                JuridicoRegistroOperaciones.objects.create(usuario=request.user.username,
                                                           fichero=filename,
                                                           operacion=OPERACIONES['Restaurar'],
                                                           resultado_operacion=resultado)

                return HttpResponse(json.dumps({'file_estado': True, 'url_file': 'Glacier', 'filename': filename}),
                                    content_type="application/json")

            elif restore_status == 'false':

                return HttpResponse(json.dumps({'file_estado': 'In progress', 'url_file': 'Glacier', 'filename': filename}),
                                    content_type="application/json")

            elif restore_status == 'true':

                descargar_s3(os.path.join(STATIC_DESCARGAS_ROOT, request.GET['tk']),
                             full_path,
                             filename,
                             BUCKETS['juridico'])

                path_localfile = os.path.join(STATIC_DESCARGAS_ROOT, request.GET['tk'], filename)
                rel_path = STATIC_DESCARGAS_URL + '/' + request.GET['tk'] + '/' + filename
                # rel_path = os.path.join(STATIC_DESCARGAS_URL, request.GET['tk'] , filename)

                if os.path.exists(path_localfile):
                    # Descarga exitosa
                    JuridicoRegistroOperaciones.objects.create(usuario=request.user.username,
                                                               fichero=filename,
                                                               operacion=OPERACIONES['Descargar'],
                                                               resultado_operacion='Success')

                    return HttpResponse(json.dumps({'file_estado': True, 'url_file': rel_path, 'filename': filename}),
                                        content_type="application/json")



    if request.is_ajax() and 'borra_archivo_filename' in request.GET:

        path = request.GET['borra_archivo_path']
        filename = request.GET['borra_archivo_filename']

        full_path = find_path_archivo(path,filename)

        response = borrar_s3_utilities(full_path, filename)

        JuridicoRegistroOperaciones.objects.create(usuario=request.user.username,
                                                   fichero=filename,
                                                   operacion=OPERACIONES['Borrar'],
                                                   resultado_operacion=response['result'])

        return HttpResponse(json.dumps(response), content_type="application/json")

    if request.is_ajax() and 'erase_files' in request.GET:

        files_string = request.GET['erase_files']

        for filename in files_string.split(';'):

            path_file = os.path.join(STATIC_SUBIDAS_ROOT, request.GET['tk'], filename)

            if os.path.exists(path_file):
                os.remove(path_file)

        return HttpResponse(json.dumps('Success'), content_type="application/json")


    context['tk'] = request.GET['tk']

    return render(request, 'juridico_app/inicio.html', context=context)


#@allowed_users(allowed_roles=['admin'])
@valid_token
def registro_operaciones(request,*args, **kwargs):
    logger.debug('[juridico_views.py][juridico_registro_operaciones]')

    context = {}
    id_empresa = request.user.id_empresa.id_empresa
    context['empresa'] = Empresas.objects.filter(id_empresa=id_empresa).values('nombre_empresa')[0]
    context['form_load'] = form_generator(form_name='registro')
    data = {}

    #sirve para la paginacion --> guardar los filtros que se seleccionaron
    if 'filtros' in request.session:
        if len(request.session['filtros'])>0:
            context['filtros'] = request.session['filtros']
        else:
            context['filtros'] = []
    else:
        context['filtros']=[]

    #formulario enviado
    if request.method == 'POST' and 'fecha_hasta' in request.POST:
        context['registro_operaciones_table'] = ""
        fecha_hasta = request.POST['fecha_hasta']
        fecha_desde = request.POST['fecha_desde']
        context['filtros'] = [fecha_hasta, fecha_desde, '', '']
        if 'usuario' in request.POST:
            usuario = tuple(request.POST.getlist('usuario'))
            context['filtros'][2]=request.POST.getlist('usuario')
        else:
            usuario = tuple()
        if 'operacion' in request.POST:
            operacion = tuple(request.POST.getlist('operacion'))
            context['filtros'][3] = request.POST.getlist('operacion')
        else:
            operacion = tuple()
        request.session['filtros']=context['filtros']
        data = registro_operaciones_filtro(fecha_hasta, fecha_desde, usuario, operacion)

    #cambiar de pagina en tabla manteniendo los filtros si habian
    elif request.method == 'GET' and 'page' in request.GET:
        if request.session['filtros']:
            filtro = request.session['filtros']
            fecha_hasta = filtro[0]
            fecha_desde = filtro[1]
            usuario = tuple(filtro[2])
            operacion = tuple(filtro[3])
            data = registro_operaciones_filtro(fecha_hasta, fecha_desde, usuario, operacion)
            context['filtros'] = [fecha_hasta, fecha_desde, filtro[2], filtro[3]]
            request.session['filtros'] = context['filtros']

        else:
            data = registro_operaciones_filtro((), (), (), ())
            request.session['filtros'] = []
            context['filtros'] = []
    #carga tabla inicial
    elif request.method == 'GET' and not request.is_ajax():
        request.session['filtros'] =[]
        context['filtros'] = []
        data = registro_operaciones_filtro((), (), (), ())
    else:
        pass

    #exportar a csv la tabla
    if request.is_ajax():
        token = request.GET['tk']
        if ('hasta' in request.GET or request.session['filtros']) and not 'borrar' in request.GET:

            #csv de la tabla seleccionada, primera pagina
            if request.GET['hasta']:
                fecha_hasta = request.GET['hasta']
                fecha_desde = request.GET['desde']
                usuarios = tuple(request.GET.getlist('usuarios[]'))
                operacion = tuple(request.GET.getlist('operacion[]'))
                request.session['filtros'] = [fecha_hasta, fecha_desde, request.GET.getlist('usuarios[]'), request.GET.getlist('operacion[]')]

            else:
                #tabla seleccionada cuando pagina >1
                filtro = request.session['filtros']
                fecha_hasta = filtro[0]
                fecha_desde = filtro[1]
                usuarios = tuple(filtro.getlist(2))
                operacion = tuple(filtro.getlist(3))
                request.session['filtros'] = [fecha_hasta, fecha_desde, filtro.getlist(2), filtro.getlist(3)]

            context['filtros'] = request.session['filtros']
            data = registro_operaciones_filtro(fecha_hasta,fecha_desde,usuarios,operacion)
            url = descargar_csv(data, token)
            return HttpResponse(json.dumps({'file_estado': True, 'url_file': url}), content_type="application/json")

        elif 'borrar' in request.GET:
            # Borramos static / descargas / token
            logger.debug('ERROR NO DEBERIA SALIR ESTO')
            path = os.path.join(STATIC_DESCARGAS_ROOT,token)
            if os.path.exists(path):
                os.remove(path)
            return HttpResponse(json.dumps('Success'), content_type="application/json")
        else:
            #csv de tabla sin filtros
            request.session['filtros'] = []
            context['filtros'] = []
            data = registro_operaciones_filtro((), (), (), ())
            url = descargar_csv(data, token)
            return HttpResponse(json.dumps({'file_estado': True, 'url_file': url}), content_type="application/json")

    tabla = RegistroOperacionesTable(data)
    RequestConfig(request, paginate={"per_page": 15}).configure(tabla)
    context['registro_operaciones_table'] = tabla
    context['tk'] = request.GET['tk']

    return render(request, 'juridico_app/registro_operaciones.html', context=context)


@valid_token
def ayuda(request, *args, **kwargs):

    context = {}
    context['tk'] = request.GET['tk']
    id_empresa = request.user.id_empresa.id_empresa
    context['empresa'] = Empresas.objects.filter(id_empresa=id_empresa).values('nombre_empresa')[0]
    s3_folder = request.user.tipo + '/' + str(id_empresa) + '/'

    if request.is_ajax() and 'descarga_ayuda' in request.GET:

        path = os.path.join(STATIC_DESCARGAS_ROOT, request.GET['tk'], 'ayuda')
        if os.path.exists(path)==False:
            os.mkdir(path)
        doc = request.GET['descarga_ayuda']
        filename = s3_folder + doc

        descargar_s3(path,
                     filename,
                     doc,
                     BUCKETS['ayuda'])

        path_url = STATIC_DESCARGAS_URL + '/' + request.GET['tk'] + '/ayuda/' + doc
        return HttpResponse(json.dumps({'file_estado': True, 'url_file': path_url}), content_type="application/json")

    nombre = []
    descripcion = []
    lista_files = []

    salida = listar_carpeta_s3_ayuda(BUCKETS['ayuda'], s3_folder)

    if salida[0]:

        lista_files = salida[1]

        for x in lista_files:

            list_path = x.split('/')

            if list_path[2]!=';':

                if len(list_path[2].split(';')) > 1:
                    nombre.append(list_path[2].split(';')[0])
                    descripcion.append(list_path[2].split(';')[1])
                else:
                    nombre.append(list_path[2])
                    descripcion.append('')

        context['pdf'] = zip(nombre, descripcion)

    return render(request, 'juridico_app/ayuda.html', context=context)
