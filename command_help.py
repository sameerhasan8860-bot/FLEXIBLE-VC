"""Shared command-help text for slash and dot command help requests."""
COMMAND_HELP={
"host":("","Start your Telegram-account hosting login flow in the bot's private DM.","/host","Only use this with your own Telegram account; the bot will prompt for your phone number."),
"unhost":("","Disconnect your hosted account and delete its saved hosted session/settings.","/unhost","This logs out the hosted Telegram authorization."),
"cancel":("","Stop an active hosting login flow.","/cancel","Use while /host is waiting for login input."),
"privategroup":("<group_id>","Configure the source voice-chat group.","/privategroup -1001234567890","The bot must be an administrator in that group."),
"status":("","Show bridge state, source/target groups, private group and audio settings.","/status","In a private group, only admins can view status."),
"join":("<target_id> [source_id]","Connect the hosted account's source and target voice chats.","/join -1002222222222 -1001111111111","If source_id is omitted, the configured source is used."),
"leave":("","Disconnect from both source and target voice chats.","/leave","The hosted account remains connected."),
"reset":("","Restore all audio controls to their default settings.","/reset","This does not unhost the account."),
"level":("<number>","Set the combined master audio profile.","/level 100","The audio engine applies its supported output bounds."),
"db":("<value>","Adjust output loudness in decibels.","/db 6","Positive values boost; negative values reduce output."),
"gain":("<value>","Set the linear output-gain multiplier.","/gain 1.5","1 represents normal linear gain."),
"bass":("<value>","Boost or reduce low-frequency energy.","/bass 8","Use a value supported by the audio engine."),
"treble":("<value>","Boost or reduce high-frequency energy.","/treble 5","Use a value supported by the audio engine."),
"echo":("<value>","Set the short feedback-echo amount.","/echo 35","Set 0 to disable the effect."),
"distortion":("<value>","Set soft saturation/distortion on relayed audio.","/distortion 40","Use a value supported by the audio engine."),
"presence":("<value>","Adjust the 2–8 kHz voice-presence band.","/presence 30","Helps voice cut through the mix."),
"air":("<value>","Adjust high-frequency shimmer above 8 kHz.","/air 25","Use a value supported by the audio engine."),
"loudmax":("<0–100>","Set the brick-wall loudness-maximizer amount.","/loudmax 90","Use the 0–100 range."),
"stereowide":("<0–100>","Set stereo-width expansion.","/stereowide 80","Use the 0–100 range."),
"bitcrush":("<0–100>","Add a digital bit-crush texture.","/bitcrush 15","Use the 0–100 range."),
"dominant":("<on|off>","Toggle host-dominant mix mode.","/dominant on | /dominant off","Requires an active voice-chat bridge."),
"hostboost":("<multiplier>","Set host voice boost relative to other speakers.","/hostboost 8","Requires an active bridge."),
}
def format_command_help(command,prefix="/"):
 key=(command or "").strip().lower().lstrip("/.")
 if key not in COMMAND_HELP:return None
 if prefix=="." and key not in {"join","leave","reset","level","db","gain","bass","treble","echo","distortion","presence","air","loudmax","stereowide","bitcrush","dominant","hostboost"}:return None
 args,info,example,note=COMMAND_HELP[key]
 usage=prefix+key+((" "+args) if args else "")
 if example.startswith("/"):example=example.replace("/",prefix,1)
 return (f"🔊 𝙁𝙇𝙀𝙓𝙄𝘽𝙇𝙀 𝙑𝘾 — {key.upper()}\n\n"
         f"𝙐𝙨𝙖𝙜𝙚:\n{usage}\n\n𝙀𝙭𝙖𝙢𝙥𝙡𝙚:\n{example}\n\n"
         f"𝙄𝙣𝙛𝙤:\n{info}\n{note}")
