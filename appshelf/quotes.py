"""Original reflections, shuffled once per application launch across origins."""
import json
import hashlib
import logging
from pathlib import Path
import random
import sqlite3


TIME_QUOTES = tuple("""时间花在哪里，生活就慢慢长成哪里的样子。
今天值得记住的，也许只是认真做完的一件小事。
给重要的事留出时间，它们才有机会发生。
一天的分量，藏在你真正投入的那些时刻里。
有些时间适合赶路，有些时间适合看看路边。
日子经过得很快，认真生活可以让它留下痕迹。
你怎样度过一个下午，也是在选择怎样度过一生。
值得的时光，回想起来往往有具体的人和事。
别急着填满今天，先想想什么值得留下。
时间无法收藏，经历可以。
专注的时候，一件小事也有自己的天地。
把眼前这一件事做好，今天就有了落点。
少一次无意识的切换，多一段完整的思考。
安静做事的片刻，会慢慢变成你的底气。
给一个念头多待一会儿，它可能会长成答案。
深入一点，常常比多打开一个窗口更有收获。
手边的事做清楚，心里的事也会少一些拥挤。
专注需要一段不被随意切碎的时间。
开始之前，先决定这一刻要交给什么。
偶尔关掉几个窗口，让思路有地方展开。
每一次选择，都在替时间安排去处。
有些事情值得提前开始，有些事情值得及时结束。
答应一件事之前，也给自己的时间留个位置。
把“以后再说”写成一个日期，事情才有机会向前。
能够放下的事情，会为在意的事情腾出空间。
选择少做一点，有时能让重要的事做得更好。
想做的事情很多，可以先认真对待其中一件。
把时间交出去之前，先问问自己是否愿意。
有些答案，要在真正开始之后才会出现。
今天做出的一个小决定，可能会改变明天的安排。
进步常常很轻，要过些日子才能听见回声。
一点一点做出来的东西，最经得起回头看。
学过的东西，需要时间从记忆变成自己的本领。
今天多理解一点，明天就少一点盲目。
熟练，是许多次笨拙没有被轻易放弃。
给成长留出反复练习的余地。
有些努力暂时没有结果，却已经改变了做事的你。
把一个问题想透，往往比记住十个答案更长久。
能够坚持的小步，日后也会成为一段路。
回头看看，你已经会做许多从前觉得很难的事。
留一点时间，什么也不安排。
休息过后，再看看刚才那个难题。
节省下来的时间，也可以用来慢一点。
合上屏幕以后，今天还有别的风景。
一天里可以有一段时间，只属于你自己。
空白留在那里，也有它的用处。
忙完之后，记得享用一点忙碌带来的自由。
让一顿饭有一顿饭的时间。
偶尔不追赶什么，听听自己现在想去哪里。
好好结束今天，也是在照顾明天。
愿意为一个人停留，是时间最朴素的表达。
有些相处很平常，后来却成了最想回去的时光。
认真听完一段话，也是把时间送给一个人。
想说的话，找个合适的今天说出来。
相聚的意义，往往就在一起度过的那些小事里。
留一些无需赶时间的见面。
关系里的许多温度，来自一次次具体的回应。
陪伴可以很简单：放下手边的事，好好待一会儿。
记得给在意的人，留一点没有被安排走的时间。
日后想起今天，愿你记得某个人的笑。
过去已经发生，接下来还有可以选择的部分。
遗憾可以提醒你，下次早点向在意的事走近。
有些事情结束以后，新的日子才慢慢有了位置。
允许自己用一段时间，理解一段经历。
改变方向的那一天，也属于向前走的日子。
旧计划没有完成，也可以从今天重新安排。
时间经过以后，有些问题会换一种问法。
当初绕过的路，也许教会了你辨认方向。
今天的你，可以给从前的决定一个新的回应。
有些告别很轻，日子却从此换了章节。
找到自己的节奏，需要一点耐心。
计划里留一点余地，生活才容得下意外。
做事有起有落，日子也有自己的潮汐。
与其催促每一分钟，不妨把下一步想清楚。
让一天有几个清楚的停顿，忙碌也会更有次序。
今天适合走多远，可以边走边判断。
稳稳做完一件事，会让后面的安排更从容。
一段舒服的节奏，能够陪你走很久。
给开始一点勇气，也给完成一点耐心。
按自己的步幅，把眼前这段路走好。
打开一个应用之前，记得自己原本想做什么。
信息总会继续出现，你可以决定看到哪里。
浏览到这里，也可以停下来想一想。
屏幕里的世界很大，窗外的天色也在变化。
把一点注意力，从滚动的内容里收回来。
工具用得顺手，就能把更多心思留给事情本身。
今天打开过许多窗口，愿其中有一个通向收获。
看看时间的去向，也是在重新认识自己的日常。
一段使用记录，可以成为明天安排时间的线索。
关掉暂时用不到的东西，给接下来的事情留点清静。
光落在桌面上的时候，今天正在发生。
走一段熟悉的路，也可能遇见新的季节。
一杯茶慢慢凉下来，也是一小段完整的时光。
普通的一天，也值得留下一个喜欢的片刻。
偶尔抬头看看，日子并不只在屏幕里经过。
把一个下午过得具体：读几页书，做一点事，见一个人。
愿今天有一件小事，让你觉得时间花得值得。
留住生活的细节，回忆才有清楚的轮廓。
明天还没有到，今天还有一小段可以认真度过。
愿你回望这些日子时，认得出自己珍惜过什么。""".splitlines())


def choose_launch_item(directory, items, key, *, rng=None):
    """Persist a bag independently of catalogue/history; each server holds its pick."""
    pool = list(items)
    if not pool:
        raise ValueError('语录候选不能为空')
    fingerprint = hashlib.sha256(json.dumps(pool, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    rng = rng or random.SystemRandom()
    connection = None
    try:
        connection = sqlite3.connect(Path(directory) / 'preferences.sqlite3', timeout=5)
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        row = connection.execute('SELECT value FROM preferences WHERE key=?', (key,)).fetchone()
        try:
            saved = json.loads(row[0]) if row else {}
            last, remaining = saved.get('last'), saved.get('remaining')
            if ((saved.get('poolHash') != fingerprint and saved.get('pool') != pool) or not isinstance(remaining, list)
                    or any(type(i) is not int or not 0 <= i < len(pool) for i in remaining)
                    or len(set(remaining)) != len(remaining) or last in remaining):
                remaining = []
        except (ValueError, AttributeError, TypeError):
            last, remaining = None, []
        if not remaining:
            remaining = list(range(len(pool)))
            rng.shuffle(remaining)
            if remaining[-1] == last:
                remaining[0], remaining[-1] = remaining[-1], remaining[0]
        selected = remaining.pop()
        value = json.dumps({'poolHash': fingerprint, 'last': selected, 'remaining': remaining}, ensure_ascii=False)
        connection.execute('INSERT OR REPLACE INTO preferences VALUES (?, ?)', (key, value))
        connection.commit()
        return pool[selected]
    except (sqlite3.Error, OSError):
        logging.getLogger('appshelf').warning('语录轮换状态暂不可用，使用本次随机语录')
        return rng.choice(pool)
    finally:
        if connection is not None:
            connection.close()


def choose_launch_quote(directory, *, rng=None):
    return choose_launch_item(directory, TIME_QUOTES, 'time-quotes', rng=rng)
