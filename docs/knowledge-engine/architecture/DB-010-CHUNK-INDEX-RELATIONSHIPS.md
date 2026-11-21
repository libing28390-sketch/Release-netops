# DB-010 Chunk and Index Relationships

## Contract summary

The V1 chunk graph distinguishes Chunk Version, Parent/Child, Neighbor, Chunk
Role (Chunk Role), and Index Version. `kb_chunk_version`, `kb_chunk_edge`, and
`kb_chunk_embedding` preserve these relationships so reindexing can publish a
new index without mutating the source document.

## Security and rollback

ACL and tenant checks are inherited from the document scope. DB-011 owns
Import Job state and DB-012 owns trace/citation evidence; their boundaries are
referenced rather than collapsed into the chunk row. A rollback removes only
an unpublished index generation and retains the V1 chunk/index evidence.

## Final conclusion

The chunk graph, ACL, DB-011, DB-012, V1, and 回滚 contract markers are
documented.

Final Conclusion: PASS
