import streamlit as st
import re
import pandas as pd
import numpy as np
from datetime import datetime

# --- 1. НАСТРОЙКИ СТРАНИЦЫ ---
st.set_page_config(
    page_title="Syndicate Odds Analyst",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. БОКОВАЯ ПАНЕЛЬ ---
with st.sidebar:
    st.header("⚙️ Банк и Риск")
    BANKROLL = st.number_input("Ваш Банк ($)", value=1000, step=100)
    KELLY_FRACTION = st.slider("Дробный Келли (Сила ставки)", 0.1, 0.5, 0.3, 0.05)
    st.info(f"Режим: {int(KELLY_FRACTION*100)}% от полного Келли")
    
    st.divider()
    st.markdown("### 📊 Легенда Рейтингов")
    st.markdown("💎 **S+** (Diamond) - Идеал. Пиннакл падает, маржа растет, Азиаты подтверждают.")
    st.markdown("🟢 **A** (Strong) - Хороший тренд или огромный валуй.")
    st.markdown("🟡 **B** (Risky) - Валуй есть, но Пиннакл сомневается (защита).")
    st.markdown("🔴 **C** (Trash) - Нет валуя или ловушка.")

# --- 3. МОЩНЫЕ ПАРСЕРЫ ---

def parse_pinnacle_full(raw_text):
    """
    Парсит Home/Draw/Away и вычисляет Payout (Маржу) для каждой точки.
    """
    data = []
    lines = raw_text.strip().split('\n')
    current_year = datetime.now().year
    
    for line in lines:
        parts = re.split(r'\s+', line.strip())
        # Нужно минимум 3 кэфа + время
        if len(parts) >= 5:
            try:
                # Пробуем найти 3 кэфа подряд (1X2)
                # Обычно они идут в начале: 1.83 3.82 4.41
                h, d, a = float(parts[0]), float(parts[1]), float(parts[2])
                
                # Расчет Payout (Теоретический возврат)
                # Формула: 1 / (1/H + 1/D + 1/A) * 100
                margin_sum = (1/h) + (1/d) + (1/a)
                payout = (1 / margin_sum) * 100
                
                # Парсим время
                date_str = f"{parts[-2]} {parts[-1]}"
                full_date_str = f"{current_year}-{date_str}"
                dt_obj = datetime.strptime(full_date_str, "%Y-%d-%m %H:%M")
                
                data.append({
                    "h": h, "d": d, "a": a,
                    "payout": payout,
                    "dt": dt_obj,
                    "time_str": date_str
                })
            except (ValueError, IndexError):
                continue

    if not data: return None
    
    # Сортируем от старого к новому
    data.sort(key=lambda x: x['dt'])
    
    return {
        "open": data[0],
        "current": data[-1],
        "history": data,
        "move_pct": (data[-1]['h'] - data[0]['h']) / data[0]['h'] * 100,
        "payout_diff": data[-1]['payout'] - data[0]['payout']
    }

def parse_market(raw_text):
    asians = []
    softs = []
    asian_names = ['sbobet', '188bet', '12bet', 'mansion88', 'singbet', 'ibcbet', 'crown']
    
    lines = raw_text.strip().split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line: 
            i += 1
            continue
            
        if not line[0].isdigit(): # Имя БК
            bookie_name = line
            if i + 2 < len(lines):
                try:
                    curr_parts = re.split(r'\s+', lines[i+1].strip())
                    open_parts = re.split(r'\s+', lines[i+2].strip())
                    
                    if curr_parts[0].replace('.','').isdigit():
                        curr_h = float(curr_parts[0])
                        open_h = float(open_parts[0])
                        
                        entry = {
                            "name": bookie_name,
                            "current": curr_h,
                            "move_pct": (curr_h - open_h) / open_h * 100
                        }
                        
                        if any(x in bookie_name.lower() for x in asian_names):
                            asians.append(entry)
                        elif "pinnacle" not in bookie_name.lower():
                            softs.append(entry)
                    i += 3
                except: i += 1
            else: i += 1
        else: i += 1
    return {"asians": asians, "softs": softs}

def calculate_kelly(odds, fair_prob, bankroll, fraction):
    b = odds - 1
    p = fair_prob
    q = 1 - p
    f = (b * p - q) / b
    if f <= 0: return 0
    return round(f * fraction * bankroll, 2)

# --- 4. ЯДРО АНАЛИЗА (ULTIMATE V3.0) ---

def analyze_syndicate_logic(pin_data):
    """Анализ '5 экранов': Тренд + Миграция маржи"""
    trend = pin_data['move_pct']
    payout_change = pin_data['payout_diff']
    
    # 1. СМАРТ (True Smart)
    # Цена падает (-), Маржа растет или стоит (+) -> Букмекер уверен, зазывает
    if trend < -1.5 and payout_change > -0.15:
        return "SMART", f"📉 Падение {trend:.1f}% подтверждено маржой"
        
    # 2. ЗАЩИТА (Defensive)
    # Цена падает (-), но Маржа тоже падает (-) -> Букмекер режет выплаты, боится
    elif trend < -1.5 and payout_change < -0.2:
        return "DEFENSIVE", f"🛡️ Падение {trend:.1f}%, но Payout упал (Защита)"
        
    # 3. ФАЛЬШЬ/ЛОВУШКА
    # Цена стоит, маржа скачет
    elif abs(trend) < 1.0 and abs(payout_change) > 0.5:
        return "NOISE", "⚠️ Шум. Странные движения маржи без тренда."
        
    else:
        return "NEUTRAL", "Без аномалий"

def run_full_analysis(pin_data, market_data):
    # 1. Базовые метрики
    avg_asian_move = 0
    if market_data['asians']:
        avg_asian_move = np.mean([x['move_pct'] for x in market_data['asians']])
    
    # 2. Синдикатный сигнал (Pinnacle Deep Dive)
    syn_signal, syn_reason = analyze_syndicate_logic(pin_data)
    
    # 3. Честная цена (Fair Price) - берем текущий кэф Пина и убираем маржу
    # Текущий Payout у нас уже посчитан точно!
    fair_prob = (1 / pin_data['current']['h']) * (pin_data['current']['payout'] / 100)
    fair_price = 1 / fair_prob
    
    results = {
        "grade": "C",
        "color": "gray",
        "title": "Нет сигнала",
        "msg": "Рынок спокоен.",
        "targets": []
    }
    
    # 4. Поиск Валуя (Targets)
    targets = []
    for soft in market_data['softs']:
        roi = (soft['current'] / fair_price) - 1
        if roi > 0.02: # Валуй > 2%
            stake = calculate_kelly(soft['current'], fair_prob, BANKROLL, KELLY_FRACTION)
            targets.append({
                "name": soft['name'],
                "odds": soft['current'],
                "roi": round(roi * 100, 1),
                "stake": stake
            })
    
    # --- ИТОГОВОЕ РЕШЕНИЕ ---
    
    # S+ (Diamond): Smart-сигнал + Азиаты подтверждают + Есть валуй
    if syn_signal == "SMART" and avg_asian_move < -1.0 and targets:
        results["grade"] = "S+"
        results["color"] = "green"
        results["title"] = "💎 DIAMOND BET"
        results["msg"] = f"Сильный синдикатный сигнал! {syn_reason}. Азиаты подтверждают."
        results["targets"] = targets
        
    # A (Strong): Просто сильный валуй (даже без тренда) ИЛИ Smart без азиатов
    elif targets:
        best_roi = max([t['roi'] for t in targets])
        if best_roi > 6.0:
            results["grade"] = "A"
            results["color"] = "green"
            results["title"] = "🔥 HUGE VALUE"
            results["msg"] = f"Найден огромный перевес {best_roi}%. Тренд не важен."
            results["targets"] = targets
        elif syn_signal == "SMART":
            results["grade"] = "A-"
            results["color"] = "green"
            results["title"] = "SMART MOVE"
            results["msg"] = "Пиннакл двигает линию умно, но азиаты молчат/нет данных."
            results["targets"] = targets
        else:
            results["grade"] = "B"
            results["color"] = "blue"
            results["title"] = "MODERATE VALUE"
            results["msg"] = "Есть математический перевес, но нет сильного движения рынка."
            results["targets"] = targets
            
    # B (Risky): Защитное движение
    elif syn_signal == "DEFENSIVE" and targets:
        results["grade"] = "B-"
        results["color"] = "orange"
        results["title"] = "DEFENSIVE / RISKY"
        results["msg"] = "Пиннакл роняет кэф, но 'прячется' (режет маржу). Осторожно."
        results["targets"] = targets

    return results, pin_data, avg_asian_move

# --- 5. ИНТЕРФЕЙС (UI) ---

st.title("👁️ Syndicate Odds Analyst v3.0")

col1, col2 = st.columns(2)
with col1:
    st.subheader("1. История Pinnacle")
    pin_input = st.text_area("Time / Home / Draw / Away...", height=200, placeholder="1.83 3.82 4.41 ... 26-11 23:58")
with col2:
    st.subheader("2. Рынок БК")
    mkt_input = st.text_area("Bookie / Current / Open...", height=200, placeholder="Bet365\n2.05 ...\n1.76 ...")

if st.button("🚀 ЗАПУСТИТЬ АНАЛИЗ", type="primary", use_container_width=True):
    if not pin_input or not mkt_input:
        st.error("Заполни оба поля!")
    else:
        pin_data = parse_pinnacle_full(pin_input)
        mkt_data = parse_market(mkt_input)
        
        if not pin_data:
            st.error("❌ Ошибка парсинга Pinnacle. Проверь формат (должно быть 3 кэфа + время).")
        else:
            res, p_data, a_move = run_full_analysis(pin_data, mkt_data)
            
            st.divider()
            
            # ЗАГОЛОВОК РЕЗУЛЬТАТА
            color_map = {"green": ":green", "blue": ":blue", "orange": ":orange", "gray": ":gray", "red": ":red"}
            c_code = color_map.get(res['color'], ":gray")
            st.header(f"{c_code}[ ГРЕЙД {res['grade']}: {res['title']} ]")
            st.info(f"**Анализ:** {res['msg']}")
            
            # МЕТРИКИ
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Pinny Move", f"{p_data['move_pct']:+.2f}%")
            m2.metric("Payout Change", f"{p_data['payout_diff']:+.2f}%", help="Миграция маржи. Если +, то букмекер уверен.")
            m3.metric("Asian Move", f"{a_move:+.2f}%")
            m4.metric("Fair Price", f"{1 / ((1/p_data['current']['h']) * (p_data['current']['payout']/100)):.2f}")

            # ТАБЛИЦА СТАВОК
            if res['targets']:
                st.subheader("🎯 Точки входа (Targets)")
                df = pd.DataFrame(res['targets'])
                st.dataframe(
                    df.style.format({"odds": "{:.2f}", "roi": "+{:.1f}%", "stake": "${:.0f}"}),
                    use_container_width=True,
                    column_config={
                        "name": "Букмекер",
                        "odds": "Кэф",
                        "roi": "ROI (Валуй)",
                        "stake": "Ставка (Kelly)"
                    }
                )
            else:
                if res['grade'] != "C":
                    st.warning("Сигнал есть, но у Софт-букмекеров нет подходящих кэфов (Валуя нет).")
            
            # ДЕТАЛИ (Для профи)
            with st.expander("🔬 Глубокие данные (Syndicate Data)"):
                st.write(f"**Start Payout:** {p_data['open']['payout']:.2f}%")
                st.write(f"**End Payout:** {p_data['current']['payout']:.2f}%")
                st.write("**Full History:**")
                st.write(p_data['history'])
