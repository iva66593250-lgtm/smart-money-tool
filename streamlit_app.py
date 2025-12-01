import streamlit as st
import re
import pandas as pd
from datetime import datetime
import numpy as np

# --- 1. НАСТРОЙКИ СТРАНИЦЫ ---
st.set_page_config(
    page_title="Smart Money Detector",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. БОКОВАЯ ПАНЕЛЬ (НАСТРОЙКИ БАНКА) ---
with st.sidebar:
    st.header("⚙️ Настройки")
    BANKROLL = st.number_input("Ваш Банк ($)", value=1000, step=100)
    KELLY_FRACTION = st.slider("Дробный Келли (Риск)", 0.1, 0.5, 0.3, 0.05)
    st.info(f"Ставим {int(KELLY_FRACTION*100)}% от полного Келли")
    st.markdown("---")
    st.markdown("**Легенда:**")
    st.markdown("🟢 **BUY** - Ставить (Валуй)")
    st.markdown("🛡️ **CONTRARIAN** - Против движения")
    st.markdown("🔴 **SKIP** - Нет валуя / Опасно")

# --- 3. ФУНКЦИИ ПАРСИНГА (СЕРДЦЕ ПРОГРАММЫ) ---

def parse_pinnacle(raw_text):
    """Парсит историю Pinnacle, сортирует по времени"""
    data = []
    lines = raw_text.strip().split('\n')
    
    current_year = datetime.now().year
    
    for line in lines:
        parts = re.split(r'\s+', line.strip())
        # Ищем строки, где есть дата формата ДД-ММ и время ЧЧ:ММ
        # Пример: 1.83 ... 26-11 23:58
        if len(parts) > 4:
            try:
                # Пытаемся найти цену (Home)
                price = float(parts[0])
                
                # Собираем дату (обычно последние 2 элемента)
                date_str = f"{parts[-2]} {parts[-1]}"
                # Добавляем год для правильной сортировки
                full_date_str = f"{current_year}-{date_str}"
                dt_obj = datetime.strptime(full_date_str, "%Y-%d-%m %H:%M")
                
                data.append({
                    "price": price,
                    "dt": dt_obj,
                    "time_str": date_str
                })
            except (ValueError, IndexError):
                continue

    # СОРТИРОВКА ПО ВРЕМЕНИ (От Старого к Новому)
    if not data:
        return None
        
    data.sort(key=lambda x: x['dt'])
    
    return {
        "open": data[0]['price'],
        "current": data[-1]['price'],
        "history": data,
        "move_pct": (data[-1]['price'] - data[0]['price']) / data[0]['price'] * 100
    }

def parse_market(raw_text):
    """Парсит рынок, разделяет на Азиатов и Софтов"""
    asians = []
    softs = []
    
    # Список азиатских маркеров
    asian_names = ['sbobet', '188bet', '12bet', 'mansion88', 'singbet', 'ibcbet', 'crown']
    
    lines = raw_text.strip().split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line: 
            i += 1
            continue
            
        # Если строка не начинается с цифры - это название БК
        if not line[0].isdigit():
            bookie_name = line
            # Ищем Current и Open (следующие строки)
            if i + 2 < len(lines):
                try:
                    curr_parts = re.split(r'\s+', lines[i+1].strip())
                    open_parts = re.split(r'\s+', lines[i+2].strip())
                    
                    if curr_parts[0].replace('.','').isdigit():
                        curr_price = float(curr_parts[0])
                        open_price = float(open_parts[0])
                        
                        entry = {
                            "name": bookie_name,
                            "current": curr_price,
                            "open": open_price,
                            "move_pct": (curr_price - open_price) / open_price * 100
                        }
                        
                        # Классификация
                        if any(x in bookie_name.lower() for x in asian_names):
                            asians.append(entry)
                        elif "pinnacle" not in bookie_name.lower(): # Исключаем сам Pinnacle из софтов
                            softs.append(entry)
                            
                    i += 3 # Пропускаем блок
                except (ValueError, IndexError):
                    i += 1
            else:
                i += 1
        else:
            i += 1
            
    return {"asians": asians, "softs": softs}

def calculate_kelly(odds, win_prob, bankroll, fraction):
    b = odds - 1
    p = win_prob
    q = 1 - p
    f = (b * p - q) / b
    if f <= 0: return 0
    return round(f * fraction * bankroll, 2)

# --- 4. ЯДРО АНАЛИЗА (DECISION ENGINE) ---

def run_analysis(pin_data, market_data):
    results = {
        "status": "NEUTRAL",
        "color": "gray",
        "msg": "Нет четкого сигнала",
        "targets": []
    }
    
    # 1. Анализ Азиатов
    avg_asian_move = 0
    if market_data['asians']:
        avg_asian_move = np.mean([x['move_pct'] for x in market_data['asians']])
    
    pin_move = pin_data['move_pct']
    
    # "Честная цена" (Fair Price) - убираем маржу Pinnacle (~2.5%)
    fair_prob = (1 / pin_data['current']) * 1.025 # Вероятность с учетом снятия маржи
    fair_price = 1 / fair_prob
    
    # --- ЛОГИКА ПАТТЕРНОВ ---
    
    # 1. SMART MONEY LEAD (Пин и Азиаты упали)
    if pin_move < -2.0 and avg_asian_move < -1.5:
        # Ищем тормозящих софтов
        lagging_softs = []
        for soft in market_data['softs']:
            # Если кэф софта > Pinnacle + 2.5% (Валуй)
            roi = (soft['current'] / fair_price) - 1
            if roi > 0.025:
                stake = calculate_kelly(soft['current'], fair_prob, BANKROLL, KELLY_FRACTION)
                lagging_softs.append({
                    "name": soft['name'],
                    "odds": soft['current'],
                    "roi": round(roi * 100, 1),
                    "stake": stake
                })
        
        if lagging_softs:
            results["status"] = "STRONG BUY"
            results["color"] = "green"
            results["msg"] = "🔥 Пиннакл и Азиаты обвалили кэф! Софты спят."
            results["targets"] = lagging_softs
        else:
            results["status"] = "TOO LATE"
            results["color"] = "orange"
            results["msg"] = "Тренд верный, но Софты уже упали. Валуя нет."
            
    # 2. PUBLIC TRAP (Софт упал, Пин стоит)
    elif abs(pin_move) < 1.0 and abs(avg_asian_move) < 1.0:
        # Проверяем, не упали ли софты массово
        avg_soft_move = np.mean([x['move_pct'] for x in market_data['softs']]) if market_data['softs'] else 0
        
        if avg_soft_move < -3.0:
            results["status"] = "TRAP WARNING"
            results["color"] = "red"
            results["msg"] = "⛔ Толпа грузит (Софты упали), но Профи (Пин+Азиаты) стоят. Не ставить!"
            
    # 3. CONTRARIAN (Защита уровня)
    elif pin_move > 0 and pin_data['current'] < pin_data['open'] * 1.05:
         # Пиннакл сходил вверх и вернулся (или бьется об уровень)
         pass # Здесь можно дописать логику возврата, если нужно
         
    return results, pin_move, avg_asian_move

# --- 5. ИНТЕРФЕЙС (UI) ---

st.title("⚽ Smart Money Detector v1.0")
st.markdown("Поиск валуя: **Pinnacle + Asians vs Softs**")

# Разметка колонок (Адаптивная)
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. История Pinnacle")
    pin_input = st.text_area("Вставь Time/Home/Draw/Away...", height=250, placeholder="1.83 3.82 4.41 ... 26-11 23:58")

with col2:
    st.subheader("2. Рынок БК")
    mkt_input = st.text_area("Вставь Bookie/Current/Open...", height=250, placeholder="Bet365\n2.05 ...\n1.76 ...")

# Кнопка запуска
if st.button("🚀 АНАЛИЗИРОВАТЬ МАТЧ", type="primary", use_container_width=True):
    
    if not pin_input or not mkt_input:
        st.error("⚠️ Ошибка: Пожалуйста, заполни оба поля данными!")
    else:
        # Запуск парсеров
        pin_data = parse_pinnacle(pin_input)
        mkt_data = parse_market(mkt_input)
        
        if not pin_data:
            st.error("❌ Не удалось распознать данные Pinnacle (проверь формат времени)")
        elif not mkt_data['softs'] and not mkt_data['asians']:
            st.error("❌ Не удалось распознать букмекеров")
        else:
            # Запуск Анализа
            res, pin_move, asian_move = run_analysis(pin_data, mkt_data)
            
            # --- ВЫВОД РЕЗУЛЬТАТОВ ---
            st.divider()
            
            # 1. Основной Статус
            color_map = {"green": ":green", "red": ":red", "orange": ":orange", "gray": ":gray"}
            color_code = color_map.get(res['color'], ":gray")
            
            st.header(f"{color_code}[ {res['status']} ]")
            st.markdown(f"**Вердикт:** {res['msg']}")
            
            # 2. Метрики (KPI)
            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("Pinnacle Move", f"{pin_move:+.2f}%", help="Изменение от открытия")
            kpi2.metric("Asian Move", f"{asian_move:+.2f}%", help="Среднее изменение по Sbobet/188bet")
            kpi3.metric("Softs Count", len(mkt_data['softs']), help="Количество распознанных софт-буков")
            
            # 3. Таблица рекомендаций (если есть)
            if res['targets']:
                st.subheader("💰 Где ставить (Target List):")
                df = pd.DataFrame(res['targets'])
                # Красивое отображение таблицы
                st.dataframe(
                    df.style.format({"odds": "{:.2f}", "roi": "+{:.1f}%", "stake": "${:.0f}"}),
                    use_container_width=True,
                    column_config={
                        "name": "Букмекер",
                        "odds": "Текущий Кэф",
                        "roi": "Валуй (ROI)",
                        "stake": "Ставка (Kelly)"
                    }
                )
            
            # 4. Детали (Экспандер)
            with st.expander("🔍 Показать технические детали"):
                st.write(f"**Pinnacle Open:** {pin_data['open']} -> **Current:** {pin_data['current']}")
                st.write(f"**Asians Detect:** {[a['name'] for a in mkt_data['asians']]}")
