# Подключаем config со всеми token и id
from config import settings_T, settings_V, settings_D

import telebot
from telebot import types
import vk_api
from vk_api import VkUpload
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
import json
import discord
import requests
from io import BytesIO
import tracemalloc
import os
import threading
import datetime

# from flask import Flask, request
# from vk_api.exceptions import VkApiError
# from discord import Intents
# import asyncio
# import aiohttp


# инициализация бота Telegram
token_tg = settings_T['token_tg']
chat_id_tg = settings_T['chat_id']
chat_with_tgbot_id = settings_T['chat_with_tgbot_id']
# Создаем объект бота
bot_tg = telebot.TeleBot(token_tg)

# авторизация в API ВКонтакте
access_token_vk = settings_V['access_token_vk']
vk_session = vk_api.VkApi(token=access_token_vk)
vk = vk_session.get_api()
upload = VkUpload(vk_session)
group_id_vk = settings_V['group_id']
longpoll = VkBotLongPoll(vk_session, group_id_vk)

# инициализация бота Discord
token_ds = settings_D['token_ds']
client_id_ds = settings_D['client_id']
channel_id_ds = settings_D['channel_id']
intents = discord.Intents().all()
tracemalloc.start()


# Обработка событий (опросы вк) в отдельном потоке
def listen_for_events():
    for event in longpoll.listen():
        if event.type == VkBotEventType.POLL_VOTE_NEW:
            # Получение данных о новом голосовании
            user_id = event.obj.get('user_id')
            poll_id = event.obj.get('poll_id')
            option_id = event.obj.get('option_id')

            # Получение полных данных об опросе
            poll_info = vk_session.method('polls.getById',
                                          {'owner_id': -int(group_id_vk), 'poll_id': poll_id,
                                           'extended': 1, 'answers': 1})
            poll_question = poll_info['question']
            poll_date = poll_info['created']
            poll_options = poll_info['answers']

            # Проверка наличия необходимых ключей в словаре event.obj
            if not all([poll_id, poll_question, user_id, option_id, poll_options]):
                print('Не удалось получить данные о голосовании')
                continue

            poll_date = datetime.datetime.fromtimestamp(poll_date).strftime('%Y-%m-%d %H:%M:%S')

            # не работает с мульти-опросами (выводит только первый выбранный вариант ответа)
            # в словаре event.obj должен быть ключ option_ids но его нет(
            list_of_answers = []
            for answer in poll_options:
                if answer['id'] in [option_id]:
                    list_of_answers.append(answer['text'])

            # Получение информации о пользователе, проголосовавшем в опросе
            user_info = vk_session.method('users.get', {'user_ids': user_id, 'lang': 'ru'})
            user_name = f"{user_info[0]['first_name']} {user_info[0]['last_name']}"
            answer_texts_str = ', '.join(list_of_answers) if list_of_answers else 'нет ответа'

            msg = f"Пользователь {user_name} ({user_id}) проголосовал в опросе '{poll_question}' ({poll_date}) за ответ(ы): {answer_texts_str}"
            bot_tg.send_message(chat_with_tgbot_id, msg)


# Запуск обработки событий в отдельном потоке
event_thread = threading.Thread(target=listen_for_events)
event_thread.start()


while True:
    @bot_tg.message_handler(commands=['start'])
    def button_message(message):
        # создаем кнопки
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        Btn1 = types.KeyboardButton("Telegram")
        Btn2 = types.KeyboardButton("Vk")
        Btn3 = types.KeyboardButton("Discord")
        Btn4 = types.KeyboardButton("All")
        markup.add(Btn1, Btn2, Btn3, Btn4)
        bot_tg.send_message(message.from_user.id, 'Выберите что вам надо', reply_markup=markup)


    @bot_tg.message_handler(content_types=['text'])
    def message_reply(message):
        # условие для выбора мессенджера
        if message.text == "All":
            bot_tg.register_next_step_handler(message, All)
        elif message.text == "Vk":
            bot_tg.register_next_step_handler(message, Vk)
        elif message.text == 'Telegram':
            bot_tg.register_next_step_handler(message, Telegram)
        elif message.text == 'Discord':
            bot_tg.register_next_step_handler(message, Discord)


    def send_photo_to_tg(message):
        photo = message.photo[-1].file_id
        bot_tg.send_photo(chat_id_tg, photo, caption=message.caption)


    def send_photo_to_vk(message):
        # Получаем объект фото максимального размера
        photo = message.photo[-1]
        # Получаем URL-адрес файла из объекта фото
        file_url = bot_tg.get_file_url(photo.file_id)
        # Скачиваем файл и сохраняем его на диск
        response = requests.get(file_url)
        with open('image.jpg', 'wb') as f:
            f.write(response.content)
        # Получаем URL-адрес сервера для загрузки фото на стену
        upload_url = vk.photos.getWallUploadServer(group_id=group_id_vk)['upload_url']
        # Загружаем фото на сервер
        with open('image.jpg', 'rb') as f:
            response = requests.post(upload_url, files={'photo': f})
        os.remove('image.jpg')
        # Сохраняем загруженное фото
        photo_data = vk.photos.saveWallPhoto(group_id=group_id_vk, server=response.json()['server'],
                                             photo=response.json()['photo'], hash=response.json()['hash'])[0]
        # Опубликовываем запись на стене группы с прикрепленным фото
        vk.wall.post(owner_id=-group_id_vk, message=message.caption,
                     attachments=f"photo{photo_data['owner_id']}_{photo_data['id']}")


    async def send_photo_to_ds(message, channel):
        # Получаем информацию о фотографии в Telegram
        photo = message.photo[-1]
        # Получаем файл фотографии по его file_id
        file_info = bot_tg.get_file(photo.file_id)
        # Скачиваем файл по ссылке file_path
        file_content = bot_tg.download_file(file_info.file_path)
        # bot_ds.loop.create_task(channel.send(file=discord.File(BytesIO(file_content), filename='photo.jpg')))
        try:
            if message.caption != '':
                await channel.send(message.caption)
        except:
            pass
        await channel.send(file=discord.File(BytesIO(file_content), filename='photo.jpg'))


    def send_doc_to_tg(message):
        file_info = bot_tg.get_file(message.document.file_id)
        file = bot_tg.download_file(file_info.file_path)
        bot_tg.send_document(chat_id_tg, file, caption=message.caption)


    def send_doc_to_vk(message):
        bot_tg.send_message(message.chat.id, "Документ в вк не удалось отправить(")
        # # Получаем объект документа
        # document = message.document
        # # Получаем URL-адрес файла из объекта документа
        # file_url = bot_tg.get_file_url(document.file_id)
        # # Скачиваем файл и сохраняем его на диск
        # response = requests.get(file_url)
        # with open(document.file_name, 'wb') as f:
        #     f.write(response.content)
        # # Получаем URL-адрес сервера для загрузки документа на стену
        # upload_url = vk.docs.getWallUploadServer(group_id=group_id_vk)['upload_url']
        # # Загружаем документ на сервер
        # with open(document.file_name, 'rb') as f:
        #     response = requests.post(upload_url, files={'file': f})
        #
        # # Сохраняем загруженный документ
        # document = vk.docs.save(file=response.json()['file'], title='Название документа')['doc']
        #
        # # Опубликовываем запись на стене группы с прикрепленным документом
        # vk.wall.post(owner_id=-group_id_vk, message='Новый пост с документом',
        #              attachments=f"doc{document['owner_id']}_{document['id']}")


    async def send_doc_to_ds(message, channel):
        # Получаем информацию о документе
        doc = message.document
        # Получаем файл документа по его file_id
        file_info = bot_tg.get_file(doc.file_id)
        # Скачиваем файл по ссылке file_path
        file_content = bot_tg.download_file(file_info.file_path)
        # Создаем объект файла для отправки в канал Discord
        file = BytesIO(file_content)
        file.name = doc.file_name
        # Отправляем файл в канал Discord
        # bot_ds.loop.create_task(channel.send(file=discord.File(file)))
        try:
            if message.caption != '':
                await channel.send(message.caption)
        except:
            pass
        await channel.send(file=discord.File(file))


    def send_poll_to_tg(message):
        # Получаем вопрос и варианты ответов опроса
        question = message.poll.question
        options = [option.text for option in message.poll.options]
        allows_multiple_answers = message.poll.allows_multiple_answers
        # is_anonymous = message.poll.is_anonymous  # Если вам нужно отправить неанонимный опрос в канал,
        # вам нужно отправлять его из учётной записи, которая имеет права администратора в этом канале.
        # не анонимные опросы можно присылать только в чат, а не в канал
        bot_tg.send_poll(chat_id_tg, question=question, options=options, is_anonymous=True,
                         allows_multiple_answers=allows_multiple_answers)


    def send_poll_to_vk(message):
        # Получаем вопрос и варианты ответов опроса
        question = message.poll.question
        options = [option.text for option in message.poll.options]
        allows_multiple_answers = message.poll.allows_multiple_answers
        is_anonymous = message.poll.is_anonymous
        add_answers = json.dumps(options, ensure_ascii=False)
        response = vk.polls.create(question=question, add_answers=add_answers, is_anonymous=int(is_anonymous),
                                   is_multiple=int(allows_multiple_answers))
        poll_id = response['id']
        # Опубликование опроса на стене
        vk.wall.post(owner_id=-group_id_vk, message='Новый опрос!', attachments=f'poll{-group_id_vk}_{poll_id}')


    def send_sticker_to_tg(message):
        sticker_file_id = message.sticker.file_id
        bot_tg.send_sticker(chat_id_tg, sticker_file_id)
        bot_tg.send_message(message.chat.id, "Стикер доставлен в тг:)")


    def All(message):
        bot_ds = discord.Client(intents=intents)

        @bot_ds.event
        async def on_ready():
            print(f'Logged in as {bot_ds.user} (ID: {bot_ds.user.id})')
            channel = bot_ds.get_channel(channel_id_ds)  # получаем id канала в который хотип отправить message
            try:
                if message.text:
                    bot_tg.send_message(chat_id=chat_id_tg, text=message.text)
                    vk.wall.post(owner_id=-group_id_vk, message=message.text)
                    await channel.send(message.text)
                    bot_tg.send_message(message.chat.id, 'Сообщение доставлено всем:)')
                elif message.photo:
                    send_photo_to_tg(message)
                    send_photo_to_vk(message)
                    await send_photo_to_ds(message, channel)
                    if message.caption is None:
                        bot_tg.send_message(message.chat.id, "Фото доставлено всем:)")
                    else:
                        bot_tg.send_message(message.chat.id, "Пост с фото доставлен всем:)")
                elif message.document:
                    send_doc_to_tg(message)
                    send_doc_to_vk(message)
                    await send_doc_to_ds(message, channel)
                    if message.caption is None:
                        bot_tg.send_message(message.chat.id, "Документ доставлен в тг и дс:)")
                    else:
                        bot_tg.send_message(message.chat.id, "Пост с документом доставлен в тг и дс:)")
                elif message.sticker:
                    send_sticker_to_tg(message)
                elif message.poll:
                    send_poll_to_tg(message)
                    send_poll_to_vk(message)
                    bot_tg.send_message(message.chat.id, "Опрос доставлен в тг и вк:)")
                else:
                    bot_tg.send_message(message.chat.id, "С таким типом данных не работаю(")
            except Exception as err:
                print(err)
                bot_tg.send_message(message.chat.id, "С таким типом данных не работаю(")
            await bot_ds.close()

        bot_ds.run(token_ds)


    def Vk(message):
        try:
            if message.text:
                vk.wall.post(owner_id=-group_id_vk, message=message.text)
                bot_tg.send_message(message.chat.id, 'Сообщение доставлено в вк:)')
            elif message.photo:
                send_photo_to_vk(message)
                if message.caption is None:
                    bot_tg.send_message(message.chat.id, "Фото доставлено в вк:)")
                else:
                    bot_tg.send_message(message.chat.id, "Пост с фото доставлен в вк:)")
            elif message.document:
                send_doc_to_vk(message)
            elif message.poll:
                send_poll_to_vk(message)
                bot_tg.send_message(message.chat.id, "Опрос доставлен в вк:)")
            else:
                bot_tg.send_message(message.chat.id, "С таким типом данных не работаю(")
        except Exception as err:
            print(err)
            bot_tg.send_message(message.chat.id, "С таким типом данных не работаю(")


    def Discord(message):
        bot_ds = discord.Client(intents=intents)

        @bot_ds.event
        async def on_ready():
            print(f'Logged in as {bot_ds.user} (ID: {bot_ds.user.id})')
            channel = bot_ds.get_channel(channel_id_ds)  # получаем id канала в который хотип отправить message
            if channel is not None:
                try:
                    if message.text:
                        await channel.send(message.text)
                        bot_tg.send_message(message.chat.id, 'Сообщение доставлено в дс:)')
                    elif message.photo:
                        await send_photo_to_ds(message, channel)
                        if message.caption is None:
                            bot_tg.send_message(message.chat.id, "Фото доставлено в дс:)")
                        else:
                            bot_tg.send_message(message.chat.id, "Пост с фото доставлен в дс:)")
                    elif message.document:
                        await send_doc_to_ds(message, channel)
                        if message.caption is None:
                            bot_tg.send_message(message.chat.id, "Документ доставлен в дс:)")
                        else:
                            bot_tg.send_message(message.chat.id, "Пост с документом доставлен в дс:)")
                    else:
                        bot_tg.send_message(message.chat.id, "С таким типом данных не работаю(")
                except Exception as err:
                    print(err)
                    bot_tg.send_message(message.chat.id, "С таким типом данных не работаю(")
            else:
                print(f'Канал с ID {channel_id_ds} не найден')
            await bot_ds.close()

        bot_ds.run(token_ds)


    def Telegram(message):
        try:
            if message.text:
                bot_tg.send_message(chat_id=chat_id_tg, text=message.text)
                bot_tg.send_message(message.chat.id, 'Сообщение доставлено в тг:)')
            elif message.photo:
                send_photo_to_tg(message)
                if message.caption is None:
                    bot_tg.send_message(message.chat.id, "Фото доставлено в тг:)")
                else:
                    bot_tg.send_message(message.chat.id, "Пост с фото доставлен в тг:)")
            elif message.document:
                send_doc_to_tg(message)
                if message.caption is None:
                    bot_tg.send_message(message.chat.id, "Документ доставлен в тг:)")
                else:
                    bot_tg.send_message(message.chat.id, "Пост с документом доставлен в тг:)")
            elif message.sticker:
                send_sticker_to_tg(message)
            elif message.poll:
                send_poll_to_tg(message)
                bot_tg.send_message(message.chat.id, "Опрос доставлен в тг:)")
            else:
                bot_tg.send_message(message.chat.id, "С таким типом данных не работаю(")
        except Exception as err:
            print(err)
            bot_tg.send_message(message.chat.id, "С таким типом данных не работаю(")


    # Запускаем бота
    bot_tg.polling()

