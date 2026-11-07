# ROBO PROEIS - fluxo desde o inicio
# Compatibilidade pretendida: Windows 8.1 32 bits, Chrome 109,
# Selenium 4.9.1 e ChromeDriver 109 (32 bits).
# O usuario/senha sao guardados no Gerenciador de Credenciais do Windows.
# O CAPTCHA e manual. EU VOU e acionado automaticamente somente apos validar a linha exata.

import argparse
import re
import unicodedata
import time
import ctypes
import getpass
from datetime import datetime, timedelta
from ctypes import wintypes

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (TimeoutException, WebDriverException, StaleElementReferenceException, ElementClickInterceptedException, UnexpectedAlertPresentException, NoAlertPresentException)

URL = 'http://www.proeis.rj.gov.br/'
CHROMEDRIVER = 'chromedriver.exe'
CRED_TARGET = 'PROEIS_Selenium_Login'

# ---------- Credenciais no Gerenciador de Credenciais do Windows ----------
class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)), ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR),
    ]

advapi = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
cred_write = advapi.CredWriteW
cred_write.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
cred_write.restype = wintypes.BOOL
cred_read = advapi.CredReadW
cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
cred_read.restype = wintypes.BOOL
cred_free = advapi.CredFree
cred_free.argtypes = [ctypes.c_void_p]
cred_free.restype = None


def obter_ou_salvar_credenciais():
    ptr = ctypes.c_void_p()
    if cred_read(CRED_TARGET, 1, 0, ctypes.byref(ptr)):
        try:
            cred = ctypes.cast(ptr, ctypes.POINTER(CREDENTIALW)).contents
            usuario = cred.UserName or ''
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize) if cred.CredentialBlobSize else b''
            senha = raw.decode('utf-16-le')
            if usuario and senha:
                print('Login recuperado do Gerenciador de Credenciais do Windows.')
                return usuario, senha
        finally:
            cred_free(ptr)

    print('\nPRIMEIRO ACESSO: informe suas credenciais. A senha nao sera exibida.')
    usuario = input('Usuario/CPF/matricula do PROEIS: ').strip()
    senha = getpass.getpass('Senha do PROEIS: ')
    if not usuario or not senha:
        raise ValueError('Usuario e senha nao podem ficar vazios.')

    blob = senha.encode('utf-16-le')
    blob_buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = CRED_TARGET
    cred.Comment = 'Credenciais locais do PROEIS para Selenium'
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = usuario
    if not cred_write(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error(), 'Falha ao salvar credenciais no Windows.')
    print('Credenciais salvas no Gerenciador de Credenciais do Windows.')
    return usuario, senha


# ---------- Navegacao ----------
def preencher_login(driver, usuario, senha):
    try:
        WebDriverWait(driver, 15).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "input[type='password']")
        )
    except TimeoutException:
        print('Nao encontrei o formulario de login. Se o site ja estiver aberto, continue manualmente.')
        return

    senhas = [e for e in driver.find_elements(By.CSS_SELECTOR, "input[type='password']") if e.is_displayed()]
    if not senhas:
        print('Campo de senha nao visivel. Faca o login manualmente.')
        return
    campos = driver.find_elements(By.CSS_SELECTOR, "input:not([type='password']):not([type='hidden'])")
    campos = [e for e in campos if e.is_displayed() and e.is_enabled()]
    usuario_campo = None
    for e in campos:
        info = ' '.join([e.get_attribute('name') or '', e.get_attribute('id') or '',
                         e.get_attribute('placeholder') or '', e.get_attribute('type') or '']).lower()
        if any(p in info for p in ('usuario', 'usuário', 'login', 'cpf', 'matricula', 'matrícula', 'email')):
            usuario_campo = e
            break
    if usuario_campo is None and campos:
        usuario_campo = campos[0]
    if usuario_campo is None:
        print('Nao identifiquei o campo de usuario. Faca o login manualmente.')
        return

    usuario_campo.clear()
    usuario_campo.send_keys(usuario)
    senhas[0].clear()
    senhas[0].send_keys(senha)
    print('Usuario e senha preenchidos. Confira e clique em ENTRAR no portal.')


def normalizar(s):
    # Ignora acentos e diferencas entre maiusculas/minusculas do portal.
    texto = unicodedata.normalize('NFKD', (s or ''))
    texto = ''.join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', texto).strip().casefold()


def clicar_opcao_visivel(driver, nome, timeout=30):
    alvo = normalizar(nome)
    fim = time.time() + timeout
    ultima = None
    while time.time() < fim:
        candidatos = driver.find_elements(By.XPATH, "//*[self::a or self::button or self::input or self::span or self::div]")
        for el in candidatos:
            try:
                if not el.is_displayed():
                    continue
                texto = el.get_attribute('value') if el.tag_name.lower() == 'input' else el.text
                if normalizar(texto) != alvo:
                    continue
                clicavel = el
                if el.tag_name.lower() not in ('a', 'button', 'input'):
                    pais = el.find_elements(By.XPATH, "ancestor::*[self::a or self::button][1]")
                    if pais:
                        clicavel = pais[0]
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", clicavel)
                try:
                    WebDriverWait(driver, 3).until(lambda d: clicavel.is_displayed() and clicavel.is_enabled())
                    clicavel.click()
                except Exception:
                    driver.execute_script('arguments[0].click();', clicavel)
                return
            except StaleElementReferenceException:
                ultima = 'A pagina mudou durante a procura.'
                break
            except Exception as exc:
                ultima = str(exc)
        time.sleep(0.5)
    raise TimeoutException("Nao localizei o item '" + nome + "'. " + (ultima or ''))


def esperar_tela_associar(driver):
    WebDriverWait(driver, 35).until(
        lambda d: 'FrmEventoAssociar.aspx' in d.current_url or 'Selecione os Filtros disponiveis' in d.page_source
    )


def selecionar_opcao_por_texto(driver, trecho, descricao, timeout=15):
    """Seleciona uma opcao de <select> visivel cujo texto contenha o trecho."""
    fim = time.time() + timeout
    while time.time() < fim:
        for elemento in driver.find_elements(By.TAG_NAME, 'select'):
            try:
                if not elemento.is_displayed() or not elemento.is_enabled():
                    continue
                seletor = Select(elemento)
                for opcao in seletor.options:
                    texto = normalizar(opcao.text)
                    if normalizar(trecho) in texto:
                        seletor.select_by_visible_text(opcao.text)
                        print(descricao + ': ' + opcao.text)
                        return True
            except Exception:
                continue
        time.sleep(0.5)
    print('Nao consegui selecionar automaticamente: ' + descricao)
    return False


def clicar_filtrar(driver, timeout=15):
    """Aciona FILTRAR sem depender das coordenadas fisicas da tela.
    O CAPTCHA continua sendo preenchido e confirmado manualmente pelo usuario.
    """
    fim = time.time() + timeout
    xpath = "//button|//input[@type='submit' or @type='button']|//a"

    while time.time() < fim:
        for el in driver.find_elements(By.XPATH, xpath):
            try:
                if not el.is_displayed() or not el.is_enabled():
                    continue

                texto = el.get_attribute('value') or el.text or ''
                if normalizar(texto) != 'filtrar':
                    continue

                # Tenta trazer o controle para a area visivel da pagina.
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                    el
                )
                time.sleep(0.3)

                # O clique via DOM evita o erro de coordenada negativa
                # reportado pelo ChromeDriver. Nao preenche nem resolve CAPTCHA.
                driver.execute_script("arguments[0].click();", el)

                # Trata o alerta que o proprio portal pode exibir.
                try:
                    alerta = WebDriverWait(driver, 3).until(EC.alert_is_present())
                    mensagem = alerta.text or ''
                    alerta.accept()
                    print('Alerta do portal apos FILTRAR: ' + mensagem)
                    # Qualquer alerta significa que o portal rejeitou a pesquisa.
                    # Nao prosseguir como se os resultados tivessem carregado.
                    return False
                except TimeoutException:
                    pass

                return True

            except StaleElementReferenceException:
                continue

        time.sleep(0.5)

    raise TimeoutException("Nao localizei o botao FILTRAR visivel e habilitado.")


def localizar_linha_alvo(driver):
    """Procura a linha inteira em tabelas/grades e encontra EU VOU dentro dela.
    A comparação ignora acentos, caixa, espaços e pontuação, mas exige todos
    os critérios na mesma linha antes de permitir qualquer clique.
    """
    seletores_linha = [
        "//tr",
        "//*[@role='row']",
        "//table//*[self::div or self::td]",
    ]
    vistos = set()
    for xpath in seletores_linha:
        for linha in driver.find_elements(By.XPATH, xpath):
            try:
                if not linha.is_displayed():
                    continue
                texto_original = re.sub(r'\s+', ' ', linha.text or '').strip()
                if not texto_original:
                    continue
                # Evita testar repetidamente o mesmo elemento/texto.
                chave = (xpath, texto_original)
                if chave in vistos:
                    continue
                vistos.add(chave)
                texto = normalizar(texto_original).upper()
                compacto = re.sub(r'[^A-Z0-9]', '', texto)

                if 'NITEROI PRESENTE CENTRO POG' not in texto:
                    continue
                if not re.search(r'(?<!\d)14:00(?::00)?(?!\d)', texto):
                    continue
                # Aceita "8 h", "8h", "8 horas".
                if not re.search(r'(?<!\d)8\s*H(?:ORAS?)?(?![A-Z])', texto):
                    continue
                # Aceita R. PRES.CASTELO BRANCO e variações de espaços/pontos.
                if 'RPRESCASTELOBRANCO' not in compacto:
                    continue

                # O PROEIS pode exibir reserva como "RESERVA - curso: N".
                # Nesse caso, "N" nao e quantidade de vagas: a palavra RESERVA
                # e o indicador que deve ser aceito, desde que a linha tenha
                # todos os demais criterios e um botao EU VOU habilitado.
                disponibilidade = re.search(r'(?<!\d)(\d+)\s*-?\s*CURSO\b', texto)
                if re.search(r'\bRESERVA\b', texto):
                    vagas_label = 'RESERVA'
                elif disponibilidade and int(disponibilidade.group(1)) > 0:
                    vagas_label = disponibilidade.group(1)
                else:
                    continue

                # Primeiro procura botão/link/input com rótulo explícito dentro da linha.
                botoes = linha.find_elements(By.XPATH,
                    ".//*[self::a or self::button or self::input or @role='button' or @onclick]")
                botao_alvo = None
                for b in botoes:
                    rotulo = normalizar((b.get_attribute('value') or '') + ' ' +
                                        (b.text or '') + ' ' +
                                        (b.get_attribute('title') or '') + ' ' +
                                        (b.get_attribute('aria-label') or ''))
                    if 'eu vou' in rotulo and b.is_displayed() and b.is_enabled():
                        botao_alvo = b
                        break

                # Se os dados vieram de um td/div interno, sobe até a menor linha
                # ancestral que contenha o botão EU VOU.
                if botao_alvo is None:
                    ancestrais = linha.find_elements(By.XPATH,
                        "./ancestor::*[self::tr or @role='row'][1]")
                    for ancestral in ancestrais:
                        for b in ancestral.find_elements(By.XPATH,
                            ".//*[self::a or self::button or self::input or @role='button' or @onclick]"):
                            rotulo = normalizar((b.get_attribute('value') or '') + ' ' +
                                                (b.text or '') + ' ' +
                                                (b.get_attribute('title') or '') + ' ' +
                                                (b.get_attribute('aria-label') or ''))
                            if 'eu vou' in rotulo and b.is_displayed() and b.is_enabled():
                                linha, botao_alvo = ancestral, b
                                break
                        if botao_alvo is not None:
                            break
                if botao_alvo is not None:
                    return linha, vagas_label, botao_alvo
            except StaleElementReferenceException:
                continue
            except Exception:
                continue
    return None, None, None



def obter_periodo_no_cmd():
    """Le datas individuais no CMD, uma por linha. ENTER vazio encerra a lista."""
    print("\\nINFORME AS DATAS INDIVIDUAIS QUE DESEJA PESQUISAR.")
    print("Digite cada data no formato DD/MM/AAAA.")
    print("Pressione ENTER em branco quando terminar.\\n")

    datas = []
    ja_informadas = set()

    while True:
        entrada = input(
            "Data {} (DD/MM/AAAA) ou ENTER para concluir: ".format(len(datas) + 1)
        ).strip()

        if not entrada:
            if datas:
                break
            print("Informe pelo menos uma data.")
            continue

        try:
            data = datetime.strptime(entrada, "%d/%m/%Y").date()
        except ValueError:
            print("Data invalida. Use o formato DD/MM/AAAA, por exemplo 15/12/2026.")
            continue

        if data in ja_informadas:
            print("Essa data ja foi informada. Digite outra ou pressione ENTER.")
            continue

        datas.append(data)
        ja_informadas.add(data)
        print("Data adicionada: " + data.strftime("%d/%m/%Y"))

    print("\\nDatas escolhidas:")
    for numero, data in enumerate(datas, start=1):
        print("  {}. {}".format(numero, data.strftime("%d/%m/%Y")))
    print("Total de datas para pesquisar:", len(datas))
    return datas


def selecionar_data_evento(driver, data_evento, timeout=15):
    """Seleciona no campo DATA EVENTO a opcao correspondente a data informada."""
    formatos = {
        data_evento.strftime('%d/%m/%Y'),
        data_evento.strftime('%Y-%m-%d'),
        data_evento.strftime('%d/%m/%y'),
        data_evento.strftime('%Y%m%d'),
    }
    fim = time.time() + timeout
    while time.time() < fim:
        for elemento in driver.find_elements(By.TAG_NAME, 'select'):
            try:
                if not elemento.is_displayed() or not elemento.is_enabled():
                    continue
                seletor = Select(elemento)
                for opcao in seletor.options:
                    texto = (opcao.text or '').strip()
                    valor = (opcao.get_attribute('value') or '').strip()
                    candidatos = {texto, valor}
                    if candidatos.intersection(formatos):
                        seletor.select_by_value(valor) if valor else seletor.select_by_visible_text(texto)
                        print('Data Evento selecionada: ' + (texto or valor))
                        return True
            except Exception:
                continue
        time.sleep(0.5)
    raise TimeoutException(
        'Nao localizei no campo DATA EVENTO a opcao para {}. '
        'Nenhuma pesquisa foi enviada.'.format(data_evento.strftime('%d/%m/%Y'))
    )

def main():
    driver = None
    try:
        # Solicita e valida todas as datas antes de iniciar o navegador.
        # Assim, a lista aparece no CMD mesmo que o Chrome apresente erro depois.
        datas_escolhidas = obter_periodo_no_cmd()

        usuario, senha = obter_ou_salvar_credenciais()
        print('\n[1/6] Abrindo o Chrome e acessando o PROEIS...')
        driver = webdriver.Chrome(service=Service(CHROMEDRIVER))
        driver.maximize_window()
        driver.get(URL)

        print('[2/6] Preparando o login...')
        preencher_login(driver, usuario, senha)
        input('\nQuando estiver logado e vendo a pagina inicial do PROEIS, volte a esta janela e pressione ENTER...')

        print('[3/6] Abrindo ESCALA...')
        clicar_opcao_visivel(driver, 'Escala', 35)
        time.sleep(2)

        print('[4/6] Abrindo NOVA INSCRICAO...')
        clicar_opcao_visivel(driver, 'Nova Inscrição', 35)
        esperar_tela_associar(driver)
        print('Tela EVENTOS > ASSOCIAR VOLUNTARIO aberta.')

        for ciclo, data_evento in enumerate(datas_escolhidas, start=1):
            print('\n' + '=' * 58)
            print('NOVA PESQUISA - DATA {} de {}: {}'.format(
                ciclo, len(datas_escolhidas), data_evento.strftime('%d/%m/%Y')
            ))
            print('=' * 58)
            print('[5/6] Configurando novamente os filtros da pesquisa...')
            convenio_ok = selecionar_opcao_por_texto(
                driver, 'SEGURANCA PRESENTE', 'Convenio SEGURANCA PRESENTE'
            )
            cpa_ok = selecionar_opcao_por_texto(
                driver, '12o BPM - 4o CPA', 'CPA 12o BPM - 4o CPA'
            )
            if not cpa_ok:
                cpa_ok = selecionar_opcao_por_texto(driver, '4º CPA', 'CPA 4º CPA')
            if not convenio_ok or not cpa_ok:
                print('ATENCAO: confira manualmente Convenio e CPA antes de continuar.')

            selecionar_data_evento(driver, data_evento)
            print('Resolva o CAPTCHA manualmente no Chrome; o robo nao tenta contorna-lo.')
            filtro_ok = False
            tentativa = 0
            while not filtro_ok:
                tentativa += 1
                input(
                    '\nPesquisa {} - tentativa {}: confira a data, atualize a imagem '
                    'do CAPTCHA se necessario, digite o codigo no Chrome e pressione '
                    'ENTER aqui para FILTRAR...'.format(ciclo, tentativa)
                )
                if clicar_filtrar(driver):
                    filtro_ok = True
                    print('Botao FILTRAR acionado. Aguardando os resultados...')
                    break

                print(
                    '\nO portal rejeitou a pesquisa. O programa NAO sera fechado. '
                    'Confira o CAPTCHA, atualize a imagem se necessario e tente novamente.'
                )
                print('A mesma data e os filtros atuais serao mantidos.')

            time.sleep(3)
            print('[6/6] Procurando a vaga exata...')
            linha, vagas, botao = localizar_linha_alvo(driver)
            if linha is None or botao is None:
                print(
                    'Nao encontrei uma linha com TODOS os criterios e o botao EU VOU: '
                    'NITEROI PRESENTE CENTRO POG | 14:00:00 | 8 h | '
                    'R. PRES.CASTELO BRANCO | disponibilidade positiva.'
                )
                print('Nenhuma inscricao foi acionada nesta data.')
            else:
                print('\nVAGA COMPATIVEL ENCONTRADA:')
                print(linha.text)
                print('Vagas indicadas pelo portal:', vagas)
                print(
                    'Validacao concluida: evento, horario, duracao, endereco e '
                    'disponibilidade correspondem.'
                )
                print('O robo acionara EU VOU automaticamente, uma unica vez nesta pesquisa.')
                print('Botao EU VOU localizado na linha validada.')
                WebDriverWait(driver, 10).until(
                    lambda d: botao.is_displayed() and botao.is_enabled()
                )
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                    botao
                )
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", botao)
                print('Acao de clique enviada ao botao EU VOU.')

                inscricao_confirmada = False
                try:
                    # Aguarda a resposta do portal e reconhece a mensagem de sucesso.
                    alerta = WebDriverWait(driver, 8).until(EC.alert_is_present())
                    mensagem = alerta.text or ''
                    print('Resposta do PROEIS: ' + mensagem)
                    mensagem_normalizada = normalizar(mensagem).casefold()
                    if (
                        'confirmacao no evento foi incluida com sucesso'
                        in mensagem_normalizada
                        or 'evento foi incluido com sucesso' in mensagem_normalizada
                        or 'inscricao realizada com sucesso' in mensagem_normalizada
                    ):
                        inscricao_confirmada = True

                    # Fecha o alerta automaticamente, sem exigir ENTER no CMD.
                    try:
                        alerta.accept()
                    except NoAlertPresentException:
                        print('O alerta ja estava fechado pelo portal.')
                except TimeoutException:
                    # Alguns retornos podem aparecer no proprio documento, sem alerta.
                    try:
                        texto_pagina = normalizar(driver.find_element(
                            By.TAG_NAME, 'body'
                        ).text or '').casefold()
                    except WebDriverException:
                        texto_pagina = ''

                    if (
                        'confirmacao no evento foi incluida com sucesso'
                        in texto_pagina
                        or 'evento foi incluido com sucesso' in texto_pagina
                        or 'inscricao realizada com sucesso' in texto_pagina
                    ):
                        inscricao_confirmada = True

                if inscricao_confirmada:
                    print(
                        'Inscricao confirmada pelo PROEIS. '
                        'Continuando automaticamente para a proxima data, se houver.'
                    )
                else:
                    print(
                        'O portal nao apresentou uma mensagem de sucesso reconhecida. '
                        'O robo vai parar para evitar repetir ou duplicar a inscricao. '
                        'Confira o resultado diretamente no PROEIS.'
                    )
                    break

            if ciclo < len(datas_escolhidas):
                print('Preparando a proxima data escolhida no CMD...')
                print('Voltando para NOVA INSCRICAO...')
                try:
                    clicar_opcao_visivel(driver, 'Nova Inscrição', 20)
                    esperar_tela_associar(driver)
                except TimeoutException:
                    print(
                        'Nao consegui abrir NOVA INSCRICAO automaticamente. '
                        'Abra manualmente EVENTOS > ASSOCIAR VOLUNTARIO no Chrome.'
                    )
                    print(
                        'Aguardando voce abrir EVENTOS > ASSOCIAR VOLUNTARIO no Chrome. '
                        'Assim que a tela carregar, o robo continuara automaticamente.'
                    )
                    esperar_tela_associar(driver)

    except TimeoutException as exc:
        print('\nTempo esgotado: ' + str(exc))
        if driver:
            print('Pagina atual:', driver.current_url)
            print('Tire uma foto da tela e desta janela do CMD, sem mostrar senha ou dados pessoais.')
        input('Pressione ENTER para fechar...')
    except WebDriverException as exc:
        print('\nErro do Chrome/ChromeDriver: ' + str(exc))
        print('Confira se o ChromeDriver e da versao 109 e de 32 bits.')
        input('Pressione ENTER para fechar...')
    except Exception as exc:
        print('\nErro: ' + repr(exc))
        input('Pressione ENTER para fechar...')
    finally:
        if driver:
            driver.quit()


if __name__ == '__main__':
    main()
