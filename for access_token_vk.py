import vk_api

app_id = ''
login = ''
password = ''
# необходимо снять 2-ухкратную аутенфикацию

vk_session = vk_api.VkApi(app_id=app_id, login=login, password=password, scope='notify,friends,photos,audio,video,stories,pages,menu,status,notes,wall,ads,offline,docs,groups,notifications,stats,email,market,phone_number')
try:
    vk_session.auth(token_only=True)
except vk_api.AuthError as error_msg:
    print(error_msg)

print(vk_session.token['access_token'])


# https://oauth.vk.com/authorize?client_id=7653462&group_ids=1,123456&display=page&redirect_uri=http://example.com/callback&scope=messages&response_type=token&v=5.131
# https://oauth.vk.com/authorize?client_id=7653462&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=notify,friends,photos,audio,video,stories,pages,menu,status,notes,wall,ads,offline,docs,groups,notifications,stats,email,market,phone_number&response_type=token&v=5.131