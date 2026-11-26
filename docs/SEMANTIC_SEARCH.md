# Semantic Search (Knowledge Base)

## Tổng quan
Semantic search dùng Elasticsearch + MongoDB + OpenAI embedding để tìm các đoạn nội dung liên quan trong kho tài liệu (PDF/audio đã index). LLM gọi tool `search_knowledge_base_tool` khi cần thông tin chuyên sâu từ knowledge base.

## Cách hoạt động
1) User query → generate embedding (`text-embedding-3-small`)  
2) kNN search trong Elasticsearch (`knowledge_vectors`)  
3) Lấy metadata gốc từ MongoDB (`knowledge_ingestion.metadata`) qua `doc_id`  
4) Trả về kết quả (content + title + source + score) cho LLM  
5) LLM dùng kết quả để trả lời, kèm trích dẫn nguồn

## Thành phần & Vị trí
- Logic + Tool: `app/core/features/knowledge_search.py`
  - `_get_es_client()`, `_get_mongo_client()`
  - `search_knowledge_base()` (core)
  - `search_knowledge_base_tool` (LangChain tool)
- Embedding: `app/core/features/embedding.py`
- Config: `app/core/config.py`
  - `KNOWLEDGE_MONGO_URI`, `KNOWLEDGE_MONGO_DB`
  - `KNOWLEDGE_ELASTICSEARCH_URL`, `KNOWLEDGE_ELASTICSEARCH_INDEX`
  - `OPENAI_EMBEDDING_MODEL` (mặc định `text-embedding-3-small`)
  - `KNOWLEDGE_SEARCH_TOP_K`
- Graph integration: `app/core/graph.py`
  - `tools = [search_tavily, search_knowledge_base_tool]`
- Notebook test: `notebooks/semantic_search.ipynb`

## Luồng gọi Tool
LLM tự quyết định:
- ON: Cần kiến thức chuyên sâu / đã có trong KB → gọi `search_knowledge_base_tool`
- OFF: Câu hỏi đơn giản / đã có context (profile + Holland) → trả lời trực tiếp
- THỜI GIAN THỰC: Thông tin mới nhất → có thể dùng `search_tavily`

## Kết quả trả về (format)
```
[1] {title}
   {content (truncate 500)}
   Source: {source}
   Doc ID: {doc_id}
   Relevance: {score}
```
LLM phải trích dẫn nguồn khi dùng kết quả KB.

## Environment cần
```
KNOWLEDGE_MONGO_URI=mongodb://localhost:27017
KNOWLEDGE_MONGO_DB=knowledge_ingestion
KNOWLEDGE_ELASTICSEARCH_URL=http://localhost:9200
KNOWLEDGE_ELASTICSEARCH_INDEX=knowledge_vectors
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

## Quy trình test nhanh (notebook `semantic_search.ipynb`)
1) Kiểm tra version client (`elasticsearch==8.11.0`)
2) Ping MongoDB + Elasticsearch, check index `knowledge_vectors`
3) Test embedding service (dimension 1536)
4) Test search service (3 query mẫu)
5) Test tool wrapper
6) Test ChatService:
   - End-to-end với câu hỏi mẫu
   - So sánh KB vs Tavily Search
7) E2E multi-turn:
   - Load `User_01.json` + `Holland_test_u1.json`
   - Chat nhiều turn trong cùng `THREAD_ID`
   - In full history (`data/history/semantic_search_e2e_multi.json`)

## Lưu ý triển khai
- Dùng client sync (Elasticsearch, pymongo) để khớp LangChain tools sync.
- Index name mặc định `knowledge_vectors`; kiểm tra index thực tế khi deploy.
- Bắt buộc dùng cùng embedding model với data đã index (`text-embedding-3-small`).
- Nếu Tavily Search chưa cấu hình, LLM sẽ trả lời fallback (không ảnh hưởng KB).

## TODO/Đề xuất tương lai
- Thêm cache embedding query
- Thêm router quyết định bắt buộc gọi KB với một số intent
- Thêm filter theo source_type / doc metadata nếu cần
