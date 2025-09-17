import sqlite3, time

DB = "groupme.sqlite"

SQL_LIKES_HEARTS = """
SELECT COUNT(*) FROM (
  SELECT DISTINCT message_id, user_id
  FROM likes
  UNION
  SELECT DISTINCT message_id, user_id
  FROM reactions
  WHERE COALESCE(NULLIF(code,''),'❤️')='❤️'
)
"""

SQL_REACTIONS_UNIFIED = """
-- unified = reactions (blank->heart) + likes that don't already have a heart reaction
SELECT
  (SELECT COUNT(*) FROM reactions)
  + (SELECT COUNT(*) FROM likes l
     WHERE NOT EXISTS (
       SELECT 1 FROM reactions r
       WHERE r.message_id=l.message_id
         AND r.user_id=l.user_id
         AND COALESCE(NULLIF(r.code,''),'❤️')='❤️'
     ))
"""

SQL_NONHEART = """
SELECT COUNT(*) FROM reactions
WHERE COALESCE(NULLIF(code,''),'❤️') <> '❤️'
"""

def get_counts(con):
    cur = con.cursor()
    messages     = cur.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    attachments  = cur.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
    likes_hearts = cur.execute(SQL_LIKES_HEARTS).fetchone()[0]
    reactions_unified = cur.execute(SQL_REACTIONS_UNIFIED).fetchone()[0]
    nonheart     = cur.execute(SQL_NONHEART).fetchone()[0]
    return messages, reactions_unified, likes_hearts, nonheart, attachments

def main():
    con = sqlite3.connect(DB)
    while True:
        m, react_all, likes_hearts, nonheart, att = get_counts(con)
        print(
            f"messages={m:,} | reactions(all)={react_all:,} | likes(hearts)={likes_hearts:,} | "
            f"non-heart reactions={nonheart:,} | attachments={att:,}  "
            f"({time.strftime('%H:%M:%S')})"
        )
        time.sleep(15)

if __name__ == "__main__":
    main()
