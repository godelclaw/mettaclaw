;configured at runtime:
(= (IRC_channel) (empty))
(= (IRC_server) (empty))
(= (IRC_port) (empty))
(= (IRC_user) (empty))
(= (commchannel) (empty))
(= (MM_URL) (empty))
(= (MM_CHANNEL_ID) (empty))
(= (MM_BOT_TOKEN) (empty))
(= (TG_BOT_TOKEN) (empty))
(= (TG_CHAT_ID) (empty))

;Connect all the channels. (configureChannel) is compiled into
;config/channel.metta by initialize.sh from config/local.toml [channel] kind
;(telegram | irc | mattermost); it keeps the configure argument a literal, which
;PeTTa requires for the specialization that follows to compile correctly:
(= (initChannels)
   (progn (println! "Initializing channels")
          (configureChannel)
          (if (== (commchannel) telegram)
              (progn (configure TG_BOT_TOKEN "")
                     (configure TG_CHAT_ID "")
                     (py-call (telegram.start_telegram (TG_BOT_TOKEN) (TG_CHAT_ID))))
              (if (== (commchannel) irc)
                  (progn (configure IRC_channel ##metta)
                         (configure IRC_server "irc.quakenet.org")
                         (configure IRC_port 6667)
                         (configure IRC_user maxbotnick)
                         (py-call (irc.start_irc (IRC_channel) (IRC_server) (IRC_port) (IRC_user))))
                  (progn (configure MM_URL "https://chat.singularitynet.io")
                         (configure MM_CHANNEL_ID "8fjrmabjx7gupy7e5kjznpt5qh")
                         (configure MM_BOT_TOKEN "")
                         (py-call (mattermost.start_mattermost (MM_URL) (MM_CHANNEL_ID) (MM_BOT_TOKEN))))))))

;Receive the latest user message considering all communication channels:
(= (receive)
   (if (== (commchannel) telegram)
       (py-call (telegram.getLastMessage))
       (if (== (commchannel) irc)
           (py-call (irc.getLastMessage))
           (py-call (mattermost.getLastMessage)))))

(= (lastMessageIsHuman)
   (if (== (commchannel) telegram)
       (== (py-call (telegram.lastMessageIsHuman)) 1)
       True))

;Send a message to all communication channels:
(= (send $msg)
   (let $safemsg (string-replace $msg  "\n" "\\n")
        (let $outmsg (py-call (helper.decode_safe_text $safemsg))
             (if (== (commchannel) irc)
                 (let $temp (cut) (py-call (irc.send_message $outmsg)))
	                 (if (== (commchannel) telegram)
	                     (let $temp (cut) (py-call (telegram.send_message $outmsg)))
	                     (let $temp (cut) (py-call (mattermost.send_message $outmsg))))))))

(= (send-telegram-chat $chat_id $msg)
   (let $safemsg (string-replace $msg  "\n" "\\n")
        (let $outmsg (py-call (helper.decode_safe_text $safemsg))
             (let $temp (cut) (py-call (telegram.send_message_to_chat $chat_id $outmsg))))))

;Search the internet for some information:
(= (search $msg)
   (let $query (py-call (helper.decode_safe_text $msg))
        (py-call (websearch.search $query))))

(= (search-tavily $msg)
   (let $query (py-call (helper.decode_safe_text $msg))
        (py-call (websearch.search_tavily $query))))

(= (search-ddg $msg)
   (let $query (py-call (helper.decode_safe_text $msg))
        (py-call (websearch.search_ddg $query))))
