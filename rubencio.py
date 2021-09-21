# -*- coding: utf-8 -*-
import importlib
import telebot
import os
import sqlite3
import uuid
import string
import unicodedata
import re
import sys
import random
import time

importlib.reload(sys)

allowed_chars_puns = string.ascii_letters + " " + string.digits + "áéíóúàèìòùäëïöü"
allowed_chars_triggers = allowed_chars_puns + "^$.*+?(){}\\[]<>=-"
version = "0.7.2"
required_validations = 1

if 'TOKEN' not in os.environ:
    print("Token faltante....")
    os._exit(1)

if 'DBLOCATION' not in os.environ:
    print("Base de datos faltante....")
    os._exit(1)

bot = telebot.TeleBot(os.environ['TOKEN'])
bot.skip_pending = True

def is_valid_regex(regexp=""):
    try:
        re.compile(regexp)
        is_valid = True
    except re.error:
        is_valid = False
    return is_valid


def load_default_puns(dbfile='puns.db', punsfile='puns.txt'):
    db = sqlite3.connect(dbfile)
    cursor = db.cursor()
    with open(os.path.expanduser(punsfile), 'r') as staticpuns:
        number = 0
        for line in staticpuns:
            number += 1
            if len(line.split('|')) == 2:
                trigger = line.split('|')[0].strip()
                if not is_valid_regex(trigger):
                    print ("Disparador de expresiones regulares incorrecto%s en la línea%s del archivo%s. No agregado" % (trigger, str(number), punsfile))
                else:
                    pun = line.split('|')[1].strip()
                    answer = cursor.execute('''SELECT count(trigger) FROM puns WHERE pun = ? AND trigger = ? AND chatid = 0''', (pun, trigger,)).fetchone()
                    if answer[0] == 0:
                        cursor.execute('''INSERT INTO puns(uuid,chatid,trigger,pun) VALUES(?,?,?,?)''', (str(uuid.uuid4()), "0", trigger, pun))
                        db.commit()
                        print ("Añadida combinación de palabras predeterminado \"%s\" para \"%s\"" % (pun, trigger))
            else:
                print ("Línea% s incorrecta en el archivo% s. No agregada" % (str(number), punsfile))
    db.close()


def db_setup(dbfile='puns.db'):
    db = sqlite3.connect(dbfile)
    cursor = db.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS puns (uuid text, chatid int, trigger text, pun text)')
    cursor.execute('CREATE TABLE IF NOT EXISTS validations (punid text, chatid int, userid text, karma int)')
    cursor.execute('CREATE TABLE IF NOT EXISTS chatoptions (chatid int, silence int, efectivity int, unique (chatid))')
    db.commit()
    db.close()
    for db_file in os.listdir('./defaultpuns/punsfiles'):
        load_default_puns(dbfile=punsdb, punsfile="./defaultpuns/punsfiles/" + db_file)


def is_chat_silenced(message="", dbfile='puns.db'):
    db = sqlite3.connect(dbfile)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT silence from chatoptions where chatid = ?''', (message.chat.id,)).fetchone()
    silence = int(answer[0] if answer is not None and answer[0] is not None else 0)
    return True if silence > time.time() else False


def silence_until(chatid=""):
    global punsdb
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT silence from chatoptions where chatid = ?''', (chatid,)).fetchone()
    return str(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(answer[0]))) if answer is not None and answer[0] is not None and int(time.time()) < int(answer[0]) else "--"


def load_chat_options(chatid=""):
    global punsdb
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT chatid,silence,efectivity from chatoptions where chatid = ?''', (chatid,)).fetchone()
    db.close()
    chatoptions = {'chatid': chatid,
                   'silence': answer[1] if answer is not None and answer[1] is not None else None,
                   'efectivity': answer[2] if answer is not None and answer[2] is not None else None}
    return chatoptions


def set_chat_options(chatoptions=""):
    global punsdb
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    chatid = chatoptions['chatid'] if chatoptions['chatid'] is not None else None
    silence = chatoptions['silence'] if chatoptions['silence'] is not None else None
    efectivity = chatoptions['efectivity'] if chatoptions['efectivity'] is not None else None
    cursor.execute('''INSERT OR REPLACE INTO chatoptions(chatid,silence,efectivity) VALUES(?,?,?)''', (chatid, silence, efectivity))
    db.commit()
    db.close()


def is_efective(chatid=""):
    global punsdb
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    random.randrange(0, 101, 2)
    answer = cursor.execute('''SELECT efectivity from chatoptions where chatid = ?''', (chatid,)).fetchone()
    return True if answer is None or answer[0] is None or int(answer[0]) >= random.randint(0, 100) else False


def efectivity(chatid=""):
    global punsdb
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT efectivity from chatoptions where chatid = ?''', (chatid,)).fetchone()
    return answer[0] if answer is not None else "100"


def find_pun(message="", dbfile='puns.db'):
    db = sqlite3.connect(dbfile)
    cursor = db.cursor()
    answer_list = []
# First, remove emojis and any other char not in the allowed chars
    clean_text = "".join(c for c in message.text.lower() if c in allowed_chars_puns).split()
# Then, remove accents from letters, ó becomes on o to be compared with the triggers list
    if clean_text != []:
        last_clean = unicodedata.normalize('NFKD', clean_text[-1])
        triggers = cursor.execute('''SELECT trigger from puns where (chatid = ? or chatid = 0) order by chatid desc''', (message.chat.id,)).fetchall()
        for i in triggers:
            if is_valid_regex(i[0]):
                regexp = re.compile('^' + i[0] + '$')
                if regexp.match(last_clean) is not None:
                    matches = cursor.execute('''SELECT uuid,pun,chatid from puns where trigger = ? AND (chatid = ? OR chatid = 0) ORDER BY chatid desc''', (i[0], message.chat.id)).fetchall()
                    for j in matches:
                        if j[1].split()[-1] != last_clean:
                            enabled = cursor.execute('''SELECT SUM(karma) from validations where punid = ? AND chatid = ?''', (j[0], message.chat.id)).fetchone()
                            if j[2] == 0 or enabled[0] >= required_validations or (bot.get_chat_members_count(message.chat.id) < required_validations and enabled[0] > 0):
                                answer_list.append(j[1])
        db.close()
        return None if answer_list == [] else random.choice(answer_list)


@bot.message_handler(commands=['rhelp'])
def help(message):
    helpmessage = '''*Comandos Disponibles*
/radd - Agregar una combinación (palabra | combinación)
/rdel - Eliminar combinación (palabra)
/rlist - Lista de combinaciones
/rsi - Aprobar combinación
/rno - Prohibir combinación
/rset - Establecer la probabilidad de responder (1-100)
/rchat - Ver estado del chat
/rhelp - Ayuda y Estado del bot

Las combinaciones de palabras se habilitarán si el karma supera % s en grupos con más de % s personas.
    - En grupos con menos personas, solo se requiere karma positivo

    Versiónn del bot: %s
    ''' % (required_validations, required_validations, version)
    bot.reply_to(message, helpmessage)

@bot.message_handler(commands=['rchat'])
def status(message):
    statusmessage = '''*Estado del Chat*

    - Rubencio silenciado hasta %s
    - Probabilidad de responder: %s%%
    - Karma % s

    ''' % (silence_until(message.chat.id), efectivity(message.chat.id), str(required_validations))
    bot.reply_to(message, statusmessage)

@bot.message_handler(commands=['rsi'])
def approve(message):
    global triggers
    global punsdb
    quote = message.text.replace('/rsi', '').strip()
    if quote == '':
        bot.reply_to(message, 'Falta la palabra para aprobar o sintaxis no válida: \"/rsi \"palabra de la combinación\"')
        return
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT count(trigger) FROM puns WHERE chatid = ? AND trigger = ?''', (message.chat.id, quote.strip(),)).fetchone()
    if answer[0] != 1:
        bot.reply_to(message, 'UUID ' + quote.strip() + ' no encontrado')
    else:
        answer = cursor.execute('''SELECT count(punid) FROM validations WHERE chatid = ? AND punid = ? AND userid = ? and karma = 1''', (message.chat.id, quote.strip(), message.from_user.id)).fetchone()
        if answer[0] >= 1:
            bot.reply_to(message, 'Ya has aprobado ' + quote + '. Solo se permite una aprobación por usuario.')
        else:
            cursor.execute('''INSERT INTO validations(punid,chatid,userid,karma) VALUES(?,?,?,1)''', (quote.strip(), message.chat.id, message.from_user.id))
            db.commit()
            answer = cursor.execute('''SELECT SUM(karma) FROM validations WHERE chatid = ? AND punid = ?''', (message.chat.id, quote.strip())).fetchone()
            bot.reply_to(message, 'Gracias por elegir ' + quote.strip() + '. El karma es ' + str(answer[0]))
    db.close()
    return


@bot.message_handler(commands=['rno'])
def ban(message):
    global triggers
    global punsdb
    quote = message.text.replace('/rno', '').strip()
    if quote == '':
        bot.reply_to(message, 'Falta la palabra para prohibir o sintaxis no válida: \"/rno \"palabra de la combinación\"')
        return
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT count(trigger) FROM puns WHERE chatid = ? AND trigger = ?''', (message.chat.id, quote.strip(),)).fetchone()
    if answer[0] != 1:
        bot.reply_to(message, 'UUID ' + quote.strip() + ' no encontrado')
    else:
        answer = cursor.execute('''SELECT count(punid) FROM validations WHERE chatid = ? AND punid = ? AND userid = ? and karma = -1''', (message.chat.id, quote.strip(), message.from_user.id)).fetchone()
        if answer[0] >= 1:
            bot.reply_to(message, 'Ya has prohibido ' + quote + '. Solo se permite una prohibición por usuario.')
        else:
            cursor.execute('''INSERT INTO validations(punid,chatid,userid,karma) VALUES(?,?,?,-1)''', (quote.strip(), message.chat.id, message.from_user.id))
            db.commit()
            answer = cursor.execute('''SELECT SUM(karma) FROM validations WHERE chatid = ? AND punid = ?''', (message.chat.id, quote.strip())).fetchone()
            bot.reply_to(message, 'Gracias elegir' + quote.strip() + '. El karma es ' + str(answer[0]))
    db.close()
    return


@bot.message_handler(commands=['radd'])
def add(message):
    global triggers
    global punsdb
    quote = message.text.replace('/radd', '')
    if quote == '' or len(quote.split('|')) != 2:
        bot.reply_to(message, 'Falta la combinación o sintaxis no válida: \"/radd \"palabra\"|\"combinación\"')
        return
    trigger = quote.split('|')[0].strip()
    for character in trigger:
        if character not in allowed_chars_triggers:
            bot.reply_to(message, 'Carácter Inválido ' + character + ' en la palabra, solo se permiten letras y números')
            return
    if not is_valid_regex(trigger):
        bot.reply_to(message, 'Regex no válido ' + trigger + ' definida como palabra ')
        return
    pun = quote.split('|')[1].strip()
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT count(trigger) FROM puns WHERE trigger = ? AND chatid = ? AND pun = ?''', (trigger, message.chat.id, pun)).fetchone()
    db.commit()
    if answer[0] != 0:
        bot.reply_to(message, 'Ya existe una palabra con esta combinación')
    else:
        punid = uuid.uuid4()
        cursor.execute('''INSERT INTO puns(uuid,chatid,trigger,pun) VALUES(?,?,?,?)''', (str(punid), message.chat.id, trigger, pun))
        cursor.execute('''INSERT INTO validations(punid,chatid,userid,karma) VALUES(?,?,?,1)''', (str(punid), message.chat.id, message.from_user.id))
        db.commit()
        #Arreglada el empledo del uuid al enviar el messaje del bot
        if bot.get_chat_members_count(message.chat.id) >= required_validations:
            bot.reply_to(message, 'Combinación **' + str(trigger) + '** agregada. Tiene que ser aprobada por ' + str(required_validations) + ' diferentes personas para ser habilitada')
        else:
            bot.reply_to(message, 'Combinación **' + str(trigger) + '** agregada. Se requiere karma positivo para habilitar la combinación de palabras')
        print ("Pun \"%s\" with trigger \"%s\" added to channel %s" % (pun, trigger, message.chat.id))
    db.close()
    return

#Arreglada la opcion de eliminar por el UUID
@bot.message_handler(commands=['rdel'])
def delete(message):
    global triggers
    global punsdb
    quote = message.text.replace('/rdel', '').strip()
    if quote == '':
        bot.reply_to(message, 'Falta la palabra para eliminar o sintaxis no válida: \"/rdel \"palabra de la combinación\"')
        return
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT count(trigger) FROM puns WHERE chatid = ? AND trigger = ?''', (message.chat.id, quote,)).fetchone()
    db.commit()
    if answer[0] != 1:
        bot.reply_to(message, 'UUID ' + quote + ' no encontrado')
    else:
        cursor.execute('''DELETE FROM puns WHERE chatid = ? and trigger = ?''', (message.chat.id, quote))
        bot.reply_to(message, 'Combinación eliminada')
        db.commit()
        print ("Pun with UUID \"%s\" deleted from channel %s" % (quote, message.chat.id))
    db.close()
    return


@bot.message_handler(commands=['roff'])
def silence(message):
    global punsdb
    quote = message.text.replace('/roff', '').strip()
    if quote == '' or not quote.isdigit():
        bot.reply_to(message, 'Falta el valor de tiempo para silenciar o sintaxis no válida: \"/roff "tiempo en minutos"')
        return
    if int(quote) > 60 or not quote.isdigit():
        bot.reply_to(message, 'Desactivar a Rubencio durante más de una hora no es divertido ☹️')
        return
    chatoptions = load_chat_options(message.chat.id)
    if chatoptions['silence'] is None or int(chatoptions['silence']) <= int(time.time()):
        chatoptions['silence'] = 60 * int(quote) + int(time.time())
    else:
        if int(chatoptions['silence']) + 60 * int(quote) - int(time.time()) >= 3600:
            bot.reply_to(message, 'Desactivar a Rubencio durante más de una hora no es divertido ☹️')
            return
        else:
            chatoptions['silence'] = 60 * int(quote) + int(chatoptions['silence'])
    set_chat_options(chatoptions)
    bot.reply_to(message, 'Rubencio se silenciará hasta ' + time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(chatoptions['silence'])))


@bot.message_handler(commands=['rset'])
def set(message):
    quote = message.text.replace('/rset', '').strip()
    if quote == '' or int(quote) > 100 or int(quote) < 0 or not quote.isdigit():
        bot.reply_to(message, 'Probabilidad no encontrada, fuera de rango o sintaxis no válida: \"/rset "probabilidad (1-100)"')
        return
    elif quote == '0':
        bot.reply_to(message, 'La probabilidad no puede ser 0, para deshabilitar a Rubencio durante un período de tiempo, use /rset"')
        return
    chatoptions = load_chat_options(message.chat.id)
    chatoptions['efectivity'] = int(quote)
    set_chat_options(chatoptions)
    bot.reply_to(message, 'Rubencio detectará las combinaciones ' + quote + '% del tiempo')


@bot.message_handler(commands=['rl'])
def list(message):
    index = "| uuid | status (karma) | trigger | pun\n"
    puns_list = ""
    global punsdb
    db = sqlite3.connect(punsdb)
    cursor = db.cursor()
    answer = cursor.execute('''SELECT * from puns WHERE (chatid = ? OR chatid = 0) ORDER BY chatid''', (message.chat.id,)).fetchall()
    db.commit()
    for i in answer:
        validations = cursor.execute('''SELECT SUM(validations.karma) FROM puns,validations WHERE puns.chatid = ? AND puns.uuid = ? AND puns.uuid == validations.punid AND puns.chatid = validations.chatid''', (message.chat.id, i[0],)).fetchone()
        if str(i[1]) == '0':
            puns_list += "| default pun | always enabled | " + str(i[2]) + " | " + str(i[3]) + "\n"
        else:
            if bot.get_chat_members_count(message.chat.id) >= required_validations:
                if validations[0] >= required_validations:
                    puns_list += "| " + str(i[0]) + " | enabled (" + str(validations[0]) + "/" + str(required_validations) + ") | " + str(i[2]) + " | " + str(i[3]) + "\n"
                else:
                    puns_list += "| " + str(i[0]) + " | disabled (" + str(validations[0]) + "/" + str(required_validations) + ") | " + str(i[2]) + " | " + str(i[3]) + "\n"
            else:
                if validations[0] > 0:
                    puns_list += "| " + str(i[0]) + " | enabled (" + str(validations[0]) + ") | " + str(i[2]) + " | " + str(i[3]) + "\n"
                else:
                    puns_list += "| " + str(i[0]) + " | disabled (" + str(validations[0]) + ") | " + str(i[2]) + " | " + str(i[3]) + "\n"
    if len(puns_list) > 4000:
        entries = puns_list.split('\n')
        output = ""
        for i in entries:
            if len(index + output + i + '\n') > 4000:
                bot.reply_to(message, index + output)
                output = i + '\n'
            else:
                output = output + i + '\n'
        bot.reply_to(message, index + output)
    else:
        bot.reply_to(message, index + puns_list)
    db.close()
    return


@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Vamos a divertirnos un rato (/rhelp) para obtener ayuda.")


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    if not is_chat_silenced(message=message, dbfile=punsdb) and is_efective(message.chat.id):
        rima = find_pun(message=message, dbfile=punsdb)
        if rima is not None:
            bot.reply_to(message, rima)


punsdb = os.path.expanduser(os.environ['DBLOCATION'])
db_setup(dbfile=punsdb)
print ("Rubencio %s ready for puns!" % (version))
bot.polling(none_stop=True)
