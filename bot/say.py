import io
import uuid

import telegram

from archive.models import LogKind, Log
from . import display, pattern
from .character_name import set_temp_name, get_temp_name
from .system import is_gm, message_text_convert, error_message, delete_message
from .display import Text, get


def get_symbol(chat_id, user_id) -> str:
    symbol = ''
    if is_gm(chat_id, user_id):
        symbol = display.GM_SYMBOL
    return symbol + ' '


def is_empty_message(text):
    return pattern.ME_REGEX.sub('', text).strip() == ''


def handle_as_say(bot: telegram.Bot, chat, job_queue, message: telegram.Message,
                  start: int, with_photo=None, **_):
    user_id = message.from_user.id
    text = message_text_convert(message)[start:]
    match = pattern.AS_REGEX.match(text)
    if match:
        name = match.group(1).strip()
        if name == '':
            return error_message(message, job_queue, get(Text.EMPTY_NAME))
        set_temp_name(chat.chat_id, user_id, name)
        text = text[match.end():]
    if not is_gm(chat.chat_id, user_id):
        return error_message(message, job_queue, get(Text.NOT_GM))
    else:
        name = get_temp_name(chat.chat_id, user_id) or ''
        if name == '':
            return error_message(message, job_queue, get(Text.AS_SYNTAX_ERROR))

    handle_say(bot, chat, job_queue, message, name, text, with_photo=with_photo)


def handle_say(bot: telegram.Bot, chat, job_queue, message: telegram.Message,
               name: str, text: str, edit_log=None, with_photo=None):
    user_id = message.from_user.id
    gm = is_gm(message.chat_id, user_id)
    text = text.strip()
    if text.startswith('me'):
        text = '.' + text

    kind = LogKind.NORMAL.value

    if is_empty_message(text) and not with_photo:
        error_message(message, job_queue, get(Text.EMPTY_MESSAGE))
        return
    elif pattern.ME_REGEX.search(text):
        send_text = pattern.ME_REGEX.sub('<b>{}</b>'.format(name), text)
        content = send_text
        kind = LogKind.ME.value
    else:
        send_text = '<b>{}</b>: {}'.format(name, text)
        content = text
    symbol = get_symbol(message.chat_id, user_id)
    send_text = symbol + send_text
    # on edit
    if edit_log:
        assert isinstance(edit_log, Log)
        edit_log.content = content
        edit_log.kind = kind
        edit_log.save()
        bot.edit_message_text(send_text, message.chat_id, edit_log.message_id, parse_mode='HTML')
        delete_message(message)
        return

    # send message or photo
    reply_to_message_id = None
    reply_log = None
    target = message.reply_to_message
    if isinstance(target, telegram.Message) and target.from_user.id == bot.id:
        reply_to_message_id = target.message_id
        reply_log = Log.objects.filter(chat=chat, message_id=reply_to_message_id).first()
    if isinstance(with_photo, telegram.PhotoSize):
        sent = message.chat.send_photo(
            photo=with_photo,
            caption=send_text,
            reply_to_message_id=reply_to_message_id,
            parse_mode='HTML',
        )
    else:
        if not chat.recording:
            send_text = '[{}] '.format(get(Text.NOT_RECORDING)) + send_text
        sent = message.chat.send_message(
            send_text,
            reply_to_message_id=reply_to_message_id,
            parse_mode='HTML',
        )

    if chat.recording:
        # record log
        created_log = Log.objects.create(
            message_id=sent.message_id,
            chat=chat,
            user_id=user_id,
            user_fullname=message.from_user.full_name,
            kind=kind,
            reply=reply_log,
            character_name=name,
            content=content,
            gm=gm,
            created=message.date,
        )
        # download and write photo file
        if isinstance(with_photo, telegram.PhotoSize):
            created_log.media.save('{}.jpeg'.format(uuid.uuid4()), io.BytesIO(b''))
            media = created_log.media.open('rb+')
            with_photo.get_file().download(out=media)
            media.close()
    delete_message(message)
