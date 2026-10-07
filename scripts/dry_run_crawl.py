import logging, collections
from app.ingest.sources import fetch_all_docs
from app.ingest.chunker import chunk_doc
logging.disable(logging.WARNING)
docs = fetch_all_docs()
by_src = collections.Counter(d.source for d in docs)
chunks = [c for d in docs for c in chunk_doc(d)]
toks = sum(c.tokens for c in chunks)
print("docs:", len(docs), dict(by_src))
print("chunks:", len(chunks), "tokens:", toks, "embed cost USD:", round(toks/1000*0.00002, 4))
print("urls:", len({d.url for d in docs}))
print("html pages:", [d.url for d in docs if d.source=="html"])
import statistics; print("chunk tokens min/median/max:", min(c.tokens for c in chunks), int(statistics.median(c.tokens for c in chunks)), max(c.tokens for c in chunks))
print("sample chunk:", chunks[0].url, "|", chunks[0].text[:200].replace("\n"," "))
