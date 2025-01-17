from functools import partial
from typing import Optional

import telegram
from django.db import transaction

from bot.tasks import update_round_message_task, answer_callback_query, edit_message, error_message, delete_message
from .system import NotGm, is_group_chat, is_gm, bot
from .patterns import INITIATIVE_REGEX
from game.models import Round, Player, Actor
from .display import Text, get_by_user, get, get_language


def round_inline_handle(_bot: telegram.Bot, query: telegram.CallbackQuery, gm: bool, game_round: Round):
    language_code = get_language(query.from_user)

    def _(x):
        return get(x, language_code)

    method = str(query.data)
    actors = game_round.get_actors()
    if method == 'round:next':
        next_count = game_round.counter + 1
        if next_count >= len(actors):
            next_count = 0
            game_round.round_counter += 1
        game_round.counter = next_count
        game_round.save()
        answer_callback_query(query.id)
        update_round_message(game_round, language_code)
    elif method == 'round:prev':
        prev_count = game_round.counter - 1
        if prev_count < 0:
            if game_round.round_counter <= 1:
                answer_callback_query(query.id, _(Text.ALREADY_FIRST_TURN))
                return
            else:
                prev_count = len(actors) - 1
                game_round.round_counter -= 1
        game_round.counter = prev_count
        answer_callback_query(query.id)
        update_round_message(game_round, language_code, refresh=True)
        game_round.save()
    elif method == 'round:remove':
        if not gm:
            raise NotGm()

        actors = game_round.get_actors()
        if len(actors) > 1:
            current = actors[game_round.counter % len(actors)]
            current.delete()
            answer_callback_query(query.id)
            update_round_message(game_round, language_code, refresh=True)
        else:
            answer_callback_query(query.id, _(Text.AT_LEAST_ONE_ACTOR), show_alert=True)
    elif method == 'round:finish':
        if not gm:
            raise NotGm()
        message: telegram.Message = query.message
        edit_message(message.chat_id, message.message_id, _(Text.ROUND_ALREADY_FINISHED))
        remove_round(game_round.chat_id)


def round_inline_callback(_bot: telegram.Bot, query: telegram.CallbackQuery, gm: bool):
    game_round = Round.objects.filter(chat_id=query.message.chat_id).first()

    def _(t: Text):
        get_by_user(t, query.from_user)
    if not isinstance(game_round, Round):
        answer_callback_query(query.id, _(Text.GAME_NOT_IN_ROUND), show_alert=True)
        return
    try:
        with transaction.atomic():
            round_inline_handle(bot, query, gm, game_round)
    except NotGm:
        answer_callback_query(query.id, _(Text.NOT_GM), show_alert=True)


def remove_round(chat_id):
    for game_round in Round.objects.filter(chat_id=chat_id).all():
        message_id = game_round.message_id
        game_round.delete()
        delete_message(chat_id, message_id)


def update_round_message(game_round: Round, language_code, refresh=False):
    update_round_message_task.delay(game_round.chat_id, language_code, refresh)


def start_round(update: telegram.Update, _context):
    message: telegram.Message = update.message
    assert isinstance(message, telegram.Message)
    _ = partial(get_by_user, user=message.from_user)
    if not is_group_chat(message.chat):
        return error_message(message, _(Text.NOT_GROUP))
    chat = message.chat
    text = '{} #round\n\n\n{}'.format(_(Text.ROUND_INDICATOR), _(Text.ROUND_INDICATOR_INIT))
    delete_message(message.chat_id, message.message_id)

    sent = chat.send_message(text, parse_mode='HTML')

    message_id = sent.message_id
    chat_id = sent.chat_id
    remove_round(chat_id)
    Round.objects.create(chat_id=chat_id, message_id=message_id, hide=False)


def get_round(update: telegram.Update) -> Optional[Round]:
    message = update.message
    assert isinstance(message, telegram.Message)
    _ = partial(get_by_user, user=message.from_user)

    if not is_group_chat(message.chat):
        return error_message(message, _(Text.NOT_GROUP))
    game_round = Round.objects.filter(chat_id=message.chat_id).first()
    if not game_round:
        return error_message(message, _(Text.GAME_NOT_IN_ROUND))
    return game_round


def hide_round(update: telegram.Update, _context):
    game_round = get_round(update)
    message = update.message
    assert isinstance(message, telegram.Message)
    language_code = get_language(message.from_user)

    def _(x):
        return get(x, language_code)

    if not game_round:
        return
    if not is_gm(message.chat_id, message.from_user.id):
        return error_message(message, _(Text.NOT_GM))
    game_round.hide = True
    game_round.save()
    update_round_message(game_round, language_code, refresh=True)
    delete_message(message.chat_id, message.message_id)


def public_round(update: telegram.Update, _context):
    message: telegram.Message = update.message
    game_round = get_round(update)
    language_code = get_language(update.message.from_user)
    if not game_round:
        return
    if not is_gm(update.message.chat_id, update.message.from_user.id):
        error_text = get_by_user(Text.NOT_GM, update.message.from_user)
        return error_message(update.message, error_text)
    game_round.hide = False
    game_round.save()
    update_round_message(game_round, language_code, refresh=True)
    delete_message(message.chat_id, message.message_id)


def next_turn(update: telegram.Update, _context):
    game_round = get_round(update)
    if not game_round:
        return
    actors = game_round.get_actors()
    next_count = game_round.counter + 1
    if next_count >= len(actors):
        next_count = 0
        game_round.round_counter += 1
    game_round.counter = next_count
    game_round.save()
    language_code = get_language(update.message.from_user)
    update_round_message(game_round, language_code, refresh=False)
    delete_message(update.message.chat_id, update.message.message_id)


def create_player(_bot: telegram.Bot, message: telegram.Message, character_name: str) -> Player:
    assert isinstance(message.from_user, telegram.User)
    administrators = bot.get_chat_administrators(message.chat_id, timeout=250)
    is_admin = False
    for admin in administrators:
        if message.from_user.id == admin.user.id:
            is_admin = True
            break
    defaults = dict(
        character_name=character_name,
        full_name=message.from_user.full_name,
        username=message.from_user.username or '',
        is_gm=is_admin,
    )
    player, created = Player.objects.update_or_create(
        defaults=defaults,
        chat_id=message.chat_id,
        user_id=message.from_user.id,
    )
    return player


def handle_initiative(message: telegram.Message, name: str, text: str, **__):
    language_code = get_language(message.from_user)

    def _(t):
        return get(t, language_code)

    text = text.strip()
    match = INITIATIVE_REGEX.match(text)
    number = text
    if match is not None:
        name = match.group(1).strip()
        number = match.group(2)
    elif not text.isnumeric() or len(text) > 4:
        usage = _(Text.INIT_USAGE)
        error_message(message, usage)
        return

    game_round = Round.objects.filter(chat_id=message.chat_id).first()
    if not isinstance(game_round, Round):
        error_message(message, _(Text.INIT_WITHOUT_ROUND))
    Actor.objects.create(belong_id=message.chat_id, name=name, value=int(number))
    update_round_message(game_round, language_code, refresh=True)
    delete_message(message.chat_id, message.message_id)
