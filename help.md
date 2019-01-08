**指令**

开头加上这些指令进行特殊发言，特殊发言会被数据库记录

*为了输入方便，所有命令开头的 "." 都可以用 "。" 代替*


/save - 停止记录
/start - 重新开始记录
`/face [面数]` - 设置默认骰子面数
`/name [角色名]` - 设置角色名
`. [...]` - 以 `.` 为开头的消息视作角色发言
`. [...] .me [...]` - 角色名占位符，描述角色行为
`.r XdY [描述]` - 投掷骰子，X或Y都可以省略
`.del` - 回复自己的一条消息，删掉这条
`.edit .[命令] ...` - 回复自己的一条消息，修改这条
`.hd XdY` - 暗骰（只有GM能查看结果）