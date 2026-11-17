type ReplyItem = { id: number };
type ThreadPost = { reply_count: number };
type ThreadPage<P, R> = { post?: P; replies?: R[]; has_more?: boolean; next_after_id?: number | null };

export async function readThreadPages<P extends ThreadPost, R extends ReplyItem>(
  read: (cursor?: number) => Promise<ThreadPage<P, R>>,
  fallbackPost: P,
  initial: boolean,
  targetReplyId?: number,
) {
  let page = await read();
  let post = page.post || fallbackPost;
  let replies = page.replies || [];
  let hasMore = typeof page.has_more === "boolean" ? page.has_more : Number(post.reply_count) > replies.length;
  let nextAfterId = page.next_after_id ?? replies.at(-1)?.id ?? null;
  while (hasMore && (!initial || (targetReplyId !== undefined && !replies.some(reply => reply.id === targetReplyId)))) {
    if (nextAfterId === null) throw new Error("The next reply page could not be located.");
    const cursor = nextAfterId;
    page = await read(cursor);
    post = page.post || post;
    const known = new Set(replies.map(reply => reply.id));
    const added = (page.replies || []).filter(reply => !known.has(reply.id));
    replies = [...replies, ...added];
    hasMore = typeof page.has_more === "boolean" ? page.has_more : Number(post.reply_count) > replies.length;
    nextAfterId = page.next_after_id ?? replies.at(-1)?.id ?? null;
    if (hasMore && (!added.length || nextAfterId === cursor)) {
      throw new Error("The server did not return the next reply page.");
    }
  }
  return { post, replies, hasMore, nextAfterId };
}
