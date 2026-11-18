import html
import random
import emoji

CUSTOM_EMOJI_IDS = (5330315110260953916,5330548129416631981,5328153642199441676,5327985597309019085,5328242530842599129,5330334557872872421,5328264868967507454,5330473040503397180,5328265985659002682,5328261566137665485,5328102858506135226,5327910963662315755,5327780229152791842,5327788866332025461,5327804693286509453,5330083950826117737,5327900260603814714,5328124324752677940,5327973880638237701,5328277302897827722,5328132455125770278,5328241908072345088,5327846801145879413,5327968636483165752,5327863684662321805,5330507911342872483,5327839903428406681,5330348082724885473,5327868160018241369,5328249913891383542,5328128825878405370,5330387184107149317,5328150824700894373,5327830763737998450,5328037493398854605,5327775607767981438,5328302591665267063,5328155793978056396,5327789282943853318,5327828328491539843,5328075177441911364,5328025089533304412,5328291179937163399,5328139073670374146,5327892254784774892,5328169683902292994,5330385633623956769,5328199783033103862,5328095183399577182,5328289573619391221,5328219462573254437,5328050386890678508,5328184372690443440,5328271393022827900,5327841591350550193,5328052993935828384,5327915765435752580,5330455074655196498,5327850357378803481,5327855588648968350,5330034696141166434,5327761447260808184,5327891258352361028,5327807905922048327,5328030819019679318,5327813399185219946,5328212362992311759,5327938382733532730,5328030806134776606,5327775955660332749,5328306169373024577,5328074765125048276,5330130156084286184,5328026622836631079,5328271143914724621,5327768035740641331,5328202248344332203,5327977995216903743,5327894204699926213,5328081808871414640,5330177465149053068,5327857985240720080,5327888376429306861,5328284776140922506,5328022435243518005,5327951783031498487,5328307281769554629,5327867094866355901,5327768198949396450,5330474182964699597,5328150614247498057,5327985262301569596,5328296321013014557,5328171225795550750,5328202493157466168,5328311585326783463,5327991176471537258,5328226373175632610,5327895059398420432,5330467091973691167)

def _replace_with_html(text):
    parts = []
    cursor = 0
    for item in emoji.emoji_list(text):
        start, end = item["match_start"], item["match_end"]
        parts.append(text[cursor:start])
        fallback = text[start:end]
        custom_id = random.choice(CUSTOM_EMOJI_IDS)
        parts.append(f'<tg-emoji emoji-id="{custom_id}">{html.escape(fallback)}</tg-emoji>')
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)

async def bot_send(method, text, *args, **kwargs):
    # aiogram's Bot.send_message takes (chat_id, text), while Message.answer
    # and edit_text take (text, ...). Existing callers pass send_message as
    # bot_send(method, chat_id, text), so normalize that order here.
    is_bot_send_message = getattr(method, "__name__", "") == "send_message"
    if is_bot_send_message:
        if not args:
            raise TypeError("bot_send(send_message) requires chat_id and text")
        chat_id = text
        original = str(args[0])
        method_args = (chat_id, *args[1:])
    else:
        original = str(text)
        method_args = args

    old_parse_mode = kwargs.pop("parse_mode", None)
    # Preserve authored HTML only when the caller explicitly requested HTML.
    # Plain command replies are escaped so placeholders like <group_id> cannot
    # break Telegram's HTML parser.
    body = original if old_parse_mode == "HTML" else html.escape(original)
    converted_body = _replace_with_html(body)
    prefix_id = random.choice(CUSTOM_EMOJI_IDS)
    converted = f'<tg-emoji emoji-id="{prefix_id}">✨</tg-emoji> {converted_body}'

    try:
        if is_bot_send_message:
            return await method(method_args[0], converted, *method_args[1:], parse_mode="HTML", **kwargs)
        return await method(converted, *method_args, parse_mode="HTML", **kwargs)
    except Exception as exc:
        # If Telegram rejects custom emoji, retain a normal emoji prefix.
        from aiogram.exceptions import TelegramBadRequest
        if not isinstance(exc, TelegramBadRequest):
            raise
        if old_parse_mode is not None:
            kwargs["parse_mode"] = old_parse_mode
        fallback_text = original
        if is_bot_send_message:
            return await method(method_args[0], "✨ " + fallback_text, *method_args[1:], **kwargs)
        return await method("✨ " + fallback_text, *method_args, **kwargs)

def telethon_entities(text, enabled):
    if not enabled:
        return []
    from telethon.tl.types import MessageEntityCustomEmoji
    entities = []
    for item in emoji.emoji_list(text):
        start, end = item["match_start"], item["match_end"]
        offset = len(text[:start].encode("utf-16-le")) // 2
        length = len(text[start:end].encode("utf-16-le")) // 2
        entities.append(MessageEntityCustomEmoji(offset=offset, length=length, document_id=int(random.choice(CUSTOM_EMOJI_IDS))))
    return entities
