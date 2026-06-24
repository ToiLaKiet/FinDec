# Schema & Prompt cho Hệ thống Trích xuất Tin tức Tài chính (Tiếng Việt)

## 1. Schema JSON đầy đủ

```json
{
  "doc_id": "string (do hệ thống của bạn gán, không cần LLM điền)",
  "language": "vi",
  "main_topic": "earnings | M&A | dividend | personnel | legal_risk | macro | market_price | other",
  "entities": [
    {
      "name": "string - tên đầy đủ xuất hiện trong bài",
      "type": "Company | Person | Organization | Government",
      "ticker": "string hoặc null - mã CP nếu có (VIC, HPG...)",
      "role_in_article": "subject | mentioned"
    }
  ],
  "events": [
    {
      "event_type": "earnings_report | ma_deal | dividend | share_issuance | personnel_change | legal_penalty | default_bankruptcy | macro_indicator | price_movement | other",
      "entities_involved": ["tên entity, khớp với mục entities ở trên"],
      "attributes": {
        "_comment": "tùy theo event_type, điền các field tương ứng bên dưới (mục 2)"
      },
      "evidence_text": "string - câu/đoạn gốc trong bài làm căn cứ trích xuất, copy nguyên văn",
      "confidence": "float 0.0-1.0 - mức độ chắc chắn của model về event này"
    }
  ],
  "sentiment": {
    "overall": "positive | negative | neutral",
    "impact_level": "high | medium | low",
    "impact_scope": "company | sector | macro"
  },
  "summary": "string - tóm tắt 1-2 câu nội dung chính của bài bằng tiếng Việt"
}
```

## 2. Attributes chi tiết theo từng `event_type`

Điền vào `attributes` tương ứng với loại event. Nếu thông tin không có trong bài, để giá trị `null`, **không tự suy diễn**.

### earnings_report (Báo cáo kết quả kinh doanh)
```json
{
  "period": "string, vd: Q2/2025, 6T2025, năm 2024",
  "revenue": {"value": "number hoặc null", "unit": "tỷ VND | triệu VND | tỷ USD", "yoy_change_pct": "number hoặc null"},
  "net_profit": {"value": "number hoặc null", "unit": "string", "yoy_change_pct": "number hoặc null"},
  "eps": {"value": "number hoặc null", "unit": "VND"},
  "vs_forecast": "beat | miss | inline | null"
}
```

### ma_deal (M&A, mua bán sáp nhập)
```json
{
  "acquirer": "string",
  "target": "string",
  "deal_value": {"value": "number hoặc null", "unit": "string"},
  "stake_pct": "number hoặc null",
  "status": "proposed | approved | completed | cancelled"
}
```

### dividend (Cổ tức / phát hành thêm)
```json
{
  "dividend_type": "cash | stock | both",
  "dividend_rate_pct": "number hoặc null",
  "ex_date": "YYYY-MM-DD hoặc null",
  "payment_date": "YYYY-MM-DD hoặc null"
}
```

### share_issuance (Phát hành cổ phiếu/trái phiếu)
```json
{
  "instrument": "share | bond",
  "volume": "number hoặc null",
  "purpose": "string hoặc null"
}
```

### personnel_change (Thay đổi nhân sự)
```json
{
  "person_name": "string",
  "role": "string, vd: Tổng giám đốc, Chủ tịch HĐQT",
  "company": "string",
  "action": "appointed | resigned | dismissed",
  "effective_date": "YYYY-MM-DD hoặc null"
}
```

### legal_penalty (Pháp lý, xử phạt)
```json
{
  "violation_type": "string",
  "penalty_amount": {"value": "number hoặc null", "unit": "string"},
  "authority": "string - cơ quan ban hành"
}
```

### default_bankruptcy (Vỡ nợ, phá sản)
```json
{
  "obligation_type": "string, vd: trái phiếu, nợ vay",
  "amount": {"value": "number hoặc null", "unit": "string"},
  "status": "default | restructuring | bankruptcy_filed"
}
```

### macro_indicator (Chỉ số vĩ mô)
```json
{
  "indicator_name": "string, vd: lãi suất điều hành, CPI, GDP",
  "value": "number hoặc null",
  "unit": "% | điểm | string",
  "period": "string"
}
```

### price_movement (Biến động giá cổ phiếu bất thường)
```json
{
  "ticker": "string",
  "price_change_pct": "number hoặc null",
  "volume": "number hoặc null",
  "trigger_reason": "string hoặc null"
}
```

---

## 3. System Prompt cho LLM

```
Bạn là hệ thống trích xuất thông tin tài chính chuyên nghiệp cho thị trường Việt Nam.
Nhiệm vụ của bạn: đọc một bài báo tài chính tiếng Việt và trích xuất thông tin theo
ĐÚNG schema JSON được cung cấp, KHÔNG thêm field nào ngoài schema.

QUY TẮC BẮT BUỘC:
1. CHỈ trích xuất thông tin CÓ THẬT trong bài. Tuyệt đối không suy diễn, không bổ sung
   số liệu hay sự kiện không được nêu rõ trong văn bản.
2. Nếu một field không có thông tin trong bài, điền giá trị null. Không bỏ trống field,
   không đoán.
3. Với mỗi event, trường "evidence_text" phải là câu/đoạn NGUYÊN VĂN trong bài, không
   diễn giải lại.
4. "confidence" phản ánh mức độ chắc chắn của bạn: 0.9-1.0 nếu thông tin rõ ràng tường minh,
   0.5-0.7 nếu phải suy luận một phần (ví dụ ngày tháng tương đối), dưới 0.5 nếu thông tin
   mơ hồ.
5. Một bài báo có thể chứa NHIỀU sự kiện (events) và NHIỀU thực thể (entities) - hãy
   trích xuất đầy đủ, không chỉ lấy 1 sự kiện chính.
6. Chuẩn hóa số liệu: quy đổi đơn vị về dạng rõ ràng (vd: "35 nghìn tỷ" -> value: 35000,
   unit: "tỷ VND"). Giữ nguyên đơn vị gốc nếu không chắc cách quy đổi.
7. Với tên công ty, ưu tiên ghi tên đầy đủ xuất hiện trong bài; nếu bài có nêu mã cổ phiếu
   (ticker) thì điền vào, không tự tra cứu nếu bài không nêu.
8. Nếu bài báo KHÔNG chứa thông tin tài chính có giá trị (ví dụ: bài quảng cáo, bài chung
   chung không có số liệu/sự kiện cụ thể), trả về events: [] và main_topic: "other".
9. Chỉ trả về JSON hợp lệ theo schema, KHÔNG kèm giải thích, KHÔNG markdown code fence,
   KHÔNG văn bản thừa trước/sau JSON.

SCHEMA: 
Điền vào `attributes` tương ứng với loại event. Nếu thông tin không có trong bài, để giá trị `null`, **không tự suy diễn**.

### earnings_report (Báo cáo kết quả kinh doanh)
```json
{
  "period": "string, vd: Q2/2025, 6T2025, năm 2024",
  "revenue": {"value": "number hoặc null", "unit": "tỷ VND | triệu VND | tỷ USD", "yoy_change_pct": "number hoặc null"},
  "net_profit": {"value": "number hoặc null", "unit": "string", "yoy_change_pct": "number hoặc null"},
  "eps": {"value": "number hoặc null", "unit": "VND"},
  "vs_forecast": "beat | miss | inline | null"
}
```

### ma_deal (M&A, mua bán sáp nhập)
```json
{
  "acquirer": "string",
  "target": "string",
  "deal_value": {"value": "number hoặc null", "unit": "string"},
  "stake_pct": "number hoặc null",
  "status": "proposed | approved | completed | cancelled"
}
```

### dividend (Cổ tức / phát hành thêm)
```json
{
  "dividend_type": "cash | stock | both",
  "dividend_rate_pct": "number hoặc null",
  "ex_date": "YYYY-MM-DD hoặc null",
  "payment_date": "YYYY-MM-DD hoặc null"
}
```

### share_issuance (Phát hành cổ phiếu/trái phiếu)
```json
{
  "instrument": "share | bond",
  "volume": "number hoặc null",
  "purpose": "string hoặc null"
}
```

### personnel_change (Thay đổi nhân sự)
```json
{
  "person_name": "string",
  "role": "string, vd: Tổng giám đốc, Chủ tịch HĐQT",
  "company": "string",
  "action": "appointed | resigned | dismissed",
  "effective_date": "YYYY-MM-DD hoặc null"
}
```

### legal_penalty (Pháp lý, xử phạt)
```json
{
  "violation_type": "string",
  "penalty_amount": {"value": "number hoặc null", "unit": "string"},
  "authority": "string - cơ quan ban hành"
}
```

### default_bankruptcy (Vỡ nợ, phá sản)
```json
{
  "obligation_type": "string, vd: trái phiếu, nợ vay",
  "amount": {"value": "number hoặc null", "unit": "string"},
  "status": "default | restructuring | bankruptcy_filed"
}
```

### macro_indicator (Chỉ số vĩ mô)
```json
{
  "indicator_name": "string, vd: lãi suất điều hành, CPI, GDP",
  "value": "number hoặc null",
  "unit": "% | điểm | string",
  "period": "string"
}
```

### price_movement (Biến động giá cổ phiếu bất thường)
```json
{
  "ticker": "string",
  "price_change_pct": "number hoặc null",
  "volume": "number hoặc null",
  "trigger_reason": "string hoặc null"
}
```
### các loại sự kiện khác

```

---

## 4. Few-shot Examples (đưa vào prompt để tăng độ chính xác)

### Ví dụ 1 — Báo cáo KQKD

**Input:**
> "Tập đoàn Hòa Phát (HPG) công bố báo cáo tài chính quý 2/2025 với doanh thu đạt 35.000 tỷ đồng, tăng 12% so với cùng kỳ năm trước. Lợi nhuận sau thuế đạt 3.200 tỷ đồng, tăng 8% so với quý 2/2024, vượt 5% so với dự báo của các công ty chứng khoán."

**Output:**
```json
{
  "language": "vi",
  "main_topic": "earnings",
  "entities": [
    {"name": "Tập đoàn Hòa Phát", "type": "Company", "ticker": "HPG", "role_in_article": "subject"}
  ],
  "events": [
    {
      "event_type": "earnings_report",
      "entities_involved": ["Tập đoàn Hòa Phát"],
      "attributes": {
        "period": "Q2/2025",
        "revenue": {"value": 35000, "unit": "tỷ VND", "yoy_change_pct": 12},
        "net_profit": {"value": 3200, "unit": "tỷ VND", "yoy_change_pct": 8},
        "eps": null,
        "vs_forecast": "beat"
      },
      "evidence_text": "doanh thu đạt 35.000 tỷ đồng, tăng 12% so với cùng kỳ năm trước. Lợi nhuận sau thuế đạt 3.200 tỷ đồng, tăng 8% so với quý 2/2024, vượt 5% so với dự báo",
      "confidence": 0.95
    }
  ],
  "sentiment": {"overall": "positive", "impact_level": "medium", "impact_scope": "company"},
  "summary": "Hòa Phát (HPG) báo lãi quý 2/2025 tăng trưởng, vượt dự báo thị trường."
}
```

### Ví dụ 2 — Nhân sự + Pháp lý (nhiều event trong 1 bài)

**Input:**
> "Ông Nguyễn Văn A vừa được bổ nhiệm làm Tổng giám đốc Công ty CP Xây dựng XYZ từ ngày 1/8/2025, thay cho người tiền nhiệm từ nhiệm. Trước đó, công ty này đã bị Ủy ban Chứng khoán Nhà nước xử phạt 500 triệu đồng do vi phạm quy định công bố thông tin."

**Output:**
```json
{
  "language": "vi",
  "main_topic": "personnel",
  "entities": [
    {"name": "Nguyễn Văn A", "type": "Person", "ticker": null, "role_in_article": "subject"},
    {"name": "Công ty CP Xây dựng XYZ", "type": "Company", "ticker": null, "role_in_article": "subject"},
    {"name": "Ủy ban Chứng khoán Nhà nước", "type": "Government", "ticker": null, "role_in_article": "mentioned"}
  ],
  "events": [
    {
      "event_type": "personnel_change",
      "entities_involved": ["Nguyễn Văn A", "Công ty CP Xây dựng XYZ"],
      "attributes": {
        "person_name": "Nguyễn Văn A",
        "role": "Tổng giám đốc",
        "company": "Công ty CP Xây dựng XYZ",
        "action": "appointed",
        "effective_date": "2025-08-01"
      },
      "evidence_text": "Ông Nguyễn Văn A vừa được bổ nhiệm làm Tổng giám đốc Công ty CP Xây dựng XYZ từ ngày 1/8/2025",
      "confidence": 0.95
    },
    {
      "event_type": "legal_penalty",
      "entities_involved": ["Công ty CP Xây dựng XYZ", "Ủy ban Chứng khoán Nhà nước"],
      "attributes": {
        "violation_type": "vi phạm quy định công bố thông tin",
        "penalty_amount": {"value": 500000000, "unit": "VND"},
        "authority": "Ủy ban Chứng khoán Nhà nước"
      },
      "evidence_text": "công ty này đã bị Ủy ban Chứng khoán Nhà nước xử phạt 500 triệu đồng do vi phạm quy định công bố thông tin",
      "confidence": 0.9
    }
  ],
  "sentiment": {"overall": "negative", "impact_level": "low", "impact_scope": "company"},
  "summary": "Công ty XYZ bổ nhiệm tân Tổng giám đốc, trước đó từng bị phạt vì vi phạm công bố thông tin."
}
```

### Ví dụ 3 — Bài không có thông tin tài chính cụ thể

**Input:**
> "Thị trường chứng khoán Việt Nam được đánh giá là có nhiều tiềm năng phát triển trong dài hạn nhờ tăng trưởng kinh tế ổn định."

**Output:**
```json
{
  "language": "vi",
  "main_topic": "other",
  "entities": [],
  "events": [],
  "sentiment": {"overall": "neutral", "impact_level": "low", "impact_scope": "macro"},
  "summary": "Bài viết đánh giá chung về tiềm năng dài hạn của thị trường chứng khoán Việt Nam, không có số liệu hoặc sự kiện cụ thể."
}
```

---

## 5. Gợi ý cấu trúc lời gọi API thực tế

```
[SYSTEM PROMPT] (mục 3, kèm full schema mục 1+2)

[USER MESSAGE]
Dưới đây là 3 ví dụ mẫu, hãy học theo format:
--- VÍ DỤ 1 ---
Input: ...
Output: ...
--- VÍ DỤ 2 ---
...
--- VÍ DỤ 3 ---
...

Bây giờ hãy trích xuất bài báo sau theo đúng format trên:
"""
{nội dung bài báo cần xử lý}
"""
```

## 6. Lưu ý khi triển khai

- **Validate output**: luôn parse JSON trả về bằng try/catch, vì LLM đôi khi trả thêm text thừa dù đã yêu cầu không. Nên strip mọi ký tự trước `{` đầu và sau `}` cuối nếu cần.
- **Cross-check số liệu**: với các field số (revenue, penalty_amount...), nên chạy thêm regex tìm số + đơn vị trong bài để so khớp với kết quả LLM, đánh dấu nghi vấn nếu lệch nhau.
- **Confidence threshold**: với event có confidence < 0.6, nên đưa vào hàng đợi review thủ công trước khi đưa vào dữ liệu tổng hợp chính thức.
- **Batch size**: gọi từng bài riêng lẻ (1 request = 1 bài) để dễ retry khi lỗi, tránh nhồi nhiều bài vào 1 request làm tăng rủi ro nhầm lẫn entity giữa các bài.
