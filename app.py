import streamlit as st
import os
import pandas as pd
import re
import io
import json
import base64
from openai import OpenAI

st.set_page_config(page_title="盘点智能识别系统", layout="wide")
st.title("📝 盘点表智能识别与业务逻辑核算系统")

# ==========================================
client = OpenAI(
    api_key=os.getenv("ZHIPU_API_KEY"), 
    base_url="https://open.bigmodel.cn/api/paas/v4"
)
# ==========================================

try:
    db = pd.read_excel("data.xlsx", dtype=str)
    db = db.fillna("")
except Exception as e:
    db = pd.DataFrame()

if 'ocr_data' not in st.session_state:
    st.session_state.ocr_data = None

uploaded_files = st.sidebar.file_uploader("上传盘点表照片（可多选）", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if uploaded_files:
    st.sidebar.success(f"已选择 {len(uploaded_files)} 张图片")
    
    if st.sidebar.button("🚀 开始批量识别"):
        with st.spinner(f"AI 正在识别 {len(uploaded_files)} 张图片，请稍候..."):
            
            all_extracted_data = []
            
            for idx, uploaded_file in enumerate(uploaded_files):
                st.sidebar.text(f"正在识别第 {idx+1}/{len(uploaded_files)} 张...")
                
                base64_image = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
                
                prompt = """
                你是一个严谨的工业盘点表识别专家。请仔细识别图片中的表格，提取每一行有效数据，输出一个严格的 JSON 数组。
                数组里的每个对象必须包含四个字段：
                1. "物料名称"：如"卷板"、"钢板"、"矩形管"、"圆钢"、"角钢"等。
                2. "物料描述"：包含所有规格和尺寸参数，如"T=14"、"180×180×14"、"24×400×32570"。
                3. "预盘点"：该行预盘点列的数字。**注意：预盘点通常是件数、根数（一般较小），不要包含尺寸里的数字！**
                4. "原图实盘总重"：如果原图实盘列有数字填数字，空白则填 ""。

                【特别警告】：
                如果物料描述里有一串很长的数字（比如 5 位数如 32570、15180），**必须完整提取为一个整体**！绝对不要把前两位分给描述、后三位分给数量！宁可把整个长数字放描述里，也不能切断！
                只输出 JSON 数组，不要输出任何其他解释文字。
                """
                
                try:
                    response = client.chat.completions.create(
                        model="glm-4v-flash",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                                ]
                            }
                        ],
                        temperature=0.1
                    )
                    result_text = response.choices[0].message.content
                    result_text = result_text.replace("```json", "").replace("```", "").strip()
                    
                    data = json.loads(result_text)
                    if isinstance(data, list):
                        all_extracted_data.extend(data)
                        
                except Exception as e:
                    st.error(f"第 {idx+1} 张图片识别失败: {e}")
                    continue
            
            if all_extracted_data:
                df = pd.DataFrame(all_extracted_data)
                for col in ["物料名称", "物料描述", "预盘点", "原图实盘总重"]:
                    if col not in df.columns:
                        df[col] = ""
                st.session_state.ocr_data = df
                st.success(f"✅ {len(uploaded_files)} 张图片全部识别完毕！请核对下方合并后的数据：")
            else:
                st.error("未能从任何图片中识别出有效数据，请检查图片清晰度。")
                st.session_state.ocr_data = None

if st.session_state.ocr_data is not None:
    st.info("提示：板类算法已开启【厚度扣减 0.25mm】的理计规则。")
    
    # 【修改点 1】：中间表格处理时，清理掉无意义的小数点
    df_display = st.session_state.ocr_data.copy()
    def format_qty(x):
        x_str = str(x).strip()
        if x_str == "" or x_str.lower() == "nan":
            return ""
        try:
            val = float(x_str)
            return int(val) if val.is_integer() else val
        except:
            return x_str
    
    df_display["预盘点"] = df_display["预盘点"].apply(format_qty)
    
    edited_df = st.data_editor(df_display, use_container_width=True, num_rows="dynamic")
    
    if st.button("📊 智能计算并生成最终报表"):
        final_data = []
        
        code_col = [c for c in db.columns if '编码' in str(c) or '编号' in str(c)]
        code_col = code_col[0] if code_col else ""
        
        for index, row in edited_df.iterrows():
            name = str(row.get("物料名称", ""))
            desc = str(row.get("物料描述", "")).replace(' ', '').replace('X', '×').replace('x', '×').replace('*', '×')
            
            orig_qty_str = str(row.get("预盘点", "")).strip()
            orig_actual_str = str(row.get("原图实盘总重", "")).strip()
            
            has_qty = False
            qty_val = 0.0
            if orig_qty_str and orig_qty_str.lower() not in ["none", "nan", "无", ""]:
                match_qty = re.findall(r'\d+\.?\d*', orig_qty_str)
                if match_qty:
                    has_qty = True
                    qty_val = float(match_qty[0])
            
            if not name and not desc:
                continue

            has_real_actual = False
            if orig_actual_str and orig_actual_str.lower() not in ["none", "nan", "无", ""]:
                if re.search(r'\d', orig_actual_str):
                    has_real_actual = True
            
            unit = "kg" if "板" in name else "m"
            
            if has_real_actual:
                calc_type = "称重"
                try:
                    actual_val = float(re.findall(r'\d+\.?\d*', orig_actual_str)[0])
                except:
                    actual_val = qty_val
                final_display_qty = qty_val if has_qty else ""
            else:
                calc_type = "理计"
                calc_qty = qty_val if has_qty else 1.0
                final_display_qty = calc_qty
                
                dim_nums = [float(n) for n in re.findall(r'\d+\.?\d*', desc)]
                
                if "板" in name:
                    unit = "kg"
                    if len(dim_nums) >= 3:
                        if len(dim_nums) > 3:
                            dim_nums.sort(reverse=True)
                            length, width, thick = dim_nums[0], dim_nums[1], dim_nums[2]
                        else:
                            thick, width, length = dim_nums[0], dim_nums[1], dim_nums[2]
                        
                        new_thick = thick - 0.25
                        if new_thick < 0: new_thick = 0 
                        
                        weight = (new_thick * width * length / 1000000) * 7.85
                        actual_val = weight * calc_qty
                    else:
                        actual_val = calc_qty 
                else:
                    unit = "m"
                    if len(dim_nums) >= 3:
                        length_mm = dim_nums[-1]
                        single_length = length_mm / 1000.0 if length_mm > 50 else length_mm
                        actual_val = calc_qty * single_length
                    else:
                        actual_val = calc_qty 

            matched = pd.DataFrame()
            if not db.empty:
                desc_nums = re.findall(r'\d+', desc)
                
                def check_match(row_data):
                    row_str = str(row_data.values).upper().replace(' ', '').replace('*', '×').replace('X', '×')
                    if name and name not in row_str: return False
                    if desc_nums and desc_nums[0] not in row_str: return False
                    return True
                
                mask = db.apply(check_match, axis=1)
                matched = db[mask]

            if not matched.empty:
                raw_code = str(matched.iloc[0][code_col]) if code_col else "未找到"
                m_code = f"'{raw_code}" if raw_code != "nan" else "未匹配到"
            else:
                m_code = "未匹配到"

            # 【修改点 2】：最终输出时，如果是整数，强制转成 int，去掉小数点
            if isinstance(final_display_qty, float) and final_display_qty.is_integer():
                final_qty_output = int(final_display_qty)
            elif isinstance(final_display_qty, str) and final_display_qty == "":
                final_qty_output = ""
            else:
                final_qty_output = final_display_qty

            final_data.append({
                "班组": "XXX",
                "盘点位置": f"C{index+1}",
                "物料编码": m_code,
                "物料名称": name,
                "物料描述": desc,
                "预盘点": final_qty_output,  # 用处理后的干净整数
                "单重": "",        
                "重量": "",        
                "单位": unit,
                "理计/称重": calc_type, 
                "实盘总重": round(actual_val, 3),
                "备注": ""
            })
        
        df_final = pd.DataFrame(final_data)
        
        st.write("### 📊 最终生成的电子盘点表")
        st.dataframe(df_final, use_container_width=True)
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_final.to_excel(writer, index=False, sheet_name='线边仓盘点表')
        
        st.download_button(
            label="📥 下载标准版 Excel 报表",
            data=buffer.getvalue(),
            file_name="盘点结果报表.xlsx",
            mime="application/vnd.ms-excel"
        )