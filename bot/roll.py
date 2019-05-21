import pickle
import re
import secrets
import uuid

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import JobQueue

import dice
from archive.models import LogKind, Log
from .pattern import LOOP_ROLL_REGEX
from .system import get_chat, error_message, message_text_convert, redis, is_gm, delay_delete_messages
from .display import Text, get


def set_dice_face(_, update, args, job_queue):
    message = update.message
    assert isinstance(message, telegram.Message)
    chat = get_chat(message.chat)
    if len(args) != 1:
        return error_message(
            message,
            job_queue,
            get(Text.SET_DEFAULT_FACE_SYNTAX).format(face=chat.default_dice_face)
        )
    try:
        face = int(args[0])
    except ValueError:
        error_message(message, job_queue, get(Text.FACE_ONLY_ALLOW_NUMBER))
        return
    chat.default_dice_face = face
    chat.save()


def handle_coc_roll(
        message: telegram.Message, command: str,
        name: str, text: str, job_queue: JobQueue, **_):
    """
    Call of Cthulhu
    """
    hide = command.find('h') != -1
    text = text.strip()
    numbers = re.findall(r'\d{1,2}', text)
    if len(numbers) == 0:
        return error_message(message, job_queue, get(Text.COC_NEED_SKILL_VALUE))

    rolled_list = [secrets.randbelow(100) + 1]
    rolled = rolled_list[0]
    modification = ''
    skill_number = int(numbers[0])
    modifier_matched = re.search('[+-]', command)
    if modifier_matched:
        modifier = modifier_matched.group(0)
        extra = 1
        if len(numbers) > 1:
            extra = int(numbers[0])
            skill_number = int(numbers[1])
        for _ in range(extra):
            rolled_list.append(secrets.randbelow(100) + 1)
        if modifier == '+':
            rolled = min(rolled_list)
            modification += '{}:'.format(get(Text.COC_BONUS_DIE))
        elif modifier == '-':
            rolled = max(rolled_list)
            modification += '{}:'.format(get(Text.COC_PENALTY_DIE))
        modification += '<code>[{}]</code> '.format(', '.join(map(str, rolled_list)))
    half_skill_number = skill_number >> 1
    skill_number_divide_5 = skill_number // 5
    if rolled == 1:
        remark = get(Text.COC_CRITICAL)
    elif rolled <= skill_number_divide_5:
        remark = get(Text.COC_EXTREME_SUCCESS)
    elif rolled <= half_skill_number:
        remark = get(Text.COC_HARD_SUCCESS)
    elif rolled <= skill_number:
        remark = get(Text.COC_REGULAR_SUCCESS)
    elif rolled == 100:
        remark = get(Text.COC_FUMBLE)
    elif rolled >= 95 and skill_number < 50:
        remark = get(Text.COC_FUMBLE)
    else:
        remark = get(Text.COC_FAIL)
    result_text = '{} → <code>{}</code> {}\n\n{}'.format(text, rolled, remark, modification)
    handle_roll(message, name, result_text, job_queue, hide)


def handle_loop_roll(message: telegram.Message, command: str, name: str, text: str, job_queue: JobQueue, **_):
    """
    Tales from the Loop
    """
    hide = command[-1] == 'h'
    text = text.strip()
    roll_match = LOOP_ROLL_REGEX.match(text)
    if not roll_match:
        return error_message(message, job_queue, get(Text.LOOP_SYNTAX_ERROR))
    number = int(roll_match.group(1))
    if number == 0:
        return error_message(message, job_queue, get(Text.LOOP_ZERO_DICE))
    counter = 0
    result_list = []
    for _ in range(number):
        result = secrets.randbelow(6) + 1
        result_list.append(str(result))
        if result == 6:
            counter += 1
    description = text[roll_match.end():]
    result_text = '<code>({}/{}) [{}]</code> {}'.format(counter, number, ', '.join(result_list), description)
    handle_roll(message, name, result_text, job_queue, hide)


def handle_normal_roll(message: telegram.Message, command: str, name: str, start: int, job_queue: JobQueue, chat, **_):
    text = message_text_convert(message)
    text = text[start:].strip()
    hide = command[-1] == 'h'
    if text.strip() == '':
        text = 'd'
    try:
        _, result_text = dice.roll(text, chat.default_dice_face)
    except dice.RollError as e:
        return error_message(message, job_queue, e.args[0])
    handle_roll(message, name, result_text, job_queue, hide)


def handle_roll(message: telegram.Message, name: str, result_text: str, job_queue: JobQueue, hide=False):
    kind = LogKind.ROLL.value
    if hide:
        roll_id = str(uuid.uuid4())
        key = 'hide_roll:{}'.format(roll_id)
        redis.set(key, pickle.dumps({
            'text': result_text,
            'chat_id': message.chat_id,
        }))
        keyboard = [[InlineKeyboardButton(get(Text.GM_LOOKUP), callback_data=key)]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        text = '<b>{}</b> {}'.format(name, get(Text.ROLL_HIDE_DICE))
        kind = LogKind.HIDE_DICE.value
    else:
        text = '{} 🎲 {}'.format(name, result_text)
        reply_markup = None
    chat = get_chat(message.chat)
    if not chat.recording:
        text = '[{}] '.format(get(Text.NOT_RECORDING)) + text
    sent = message.chat.send_message(
        text,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )
    user = message.from_user
    assert isinstance(user, telegram.User)
    if chat.recording:
        Log.objects.create(
            user_id=user.id,
            message_id=sent.message_id,
            chat=chat,
            content=result_text,
            user_fullname=user.full_name,
            character_name=name,
            gm=is_gm(message.chat_id, user.id),
            kind=kind,
            created=message.date,
        )
    context = dict(
        chat_id=message.chat_id,
        message_id_list=[message.message_id]
    )
    job_queue.run_once(delay_delete_messages, 10, context)


def hide_roll_callback(_, update):
    query = update.callback_query
    assert isinstance(query, telegram.CallbackQuery)
    gm = is_gm(query.message.chat_id, query.from_user.id)
    data = query.data or ''
    if not gm:
        query.answer(get(Text.ONLY_GM_CAN_LOOKUP), show_alert=True)
    result = redis.get(data)
    if result:
        data = pickle.loads(result)
        text = data['text'].replace('<code>', '').replace('</code>', '')
    else:
        text = get(Text.HIDE_ROLL_NOT_FOUND)
    query.answer(
        show_alert=True,
        text=text,
        cache_time=10000,
    )
