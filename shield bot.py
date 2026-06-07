#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTF "SHIELD" - Мобильная Оперативная Группа Фонда SAI
Задачи: Защита основной группы, мониторинг динамических групп, логирование, алерты

Руководитель: Глеб Головков
Фонд: SAI (Сдерживание Аномалий в Интернете)
Цель наблюдения: Слава Ляпунов (бывший IPS-0000, бог-наблюдатель) @Orushiy_Ded
"""

import os
import json
import logging
import re
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

import telebot
from telebot.types import Message
from dotenv import load_dotenv

# ==================== ЗАГРУЗКА КОНФИГУРАЦИИ ====================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в .env файле")

# ==================== КОНСТАНТЫ (РЕДАКТИРУЮТСЯ ВРУЧНУЮ) ====================

# Три фиксированные группы
PROTECTED_MAIN_GROUP = "@MainSai"      # Основная группа для полной защиты
LOGS_CHANNEL = "@SaiLogs"              # Канал для публичных логов (с цензурой)
ALERTS_CHANNEL = "@AlertsSai"          # Канал для экстренных алертов

# Цель наблюдения (Слава Ляпунов - бог-наблюдатель)
TARGET_USERNAME = "@Orushiy_Ded"       # Логируем только его сообщения

# ID получателей алертов в ЛС
ALERT_IDS: List[int] = [2035033596]    # Головков

# ID владельца (полные права)
OWNER_ID = 2035033596

# ==================== НАСТРОЙКИ ФИЛЬТРАЦИИ ====================

# Опасные слова (триггеры CLEANER - удаление сообщений)
CLEANER_TRIGGERS: List[str] = [
    "sai-###", "sai###", "темная личность", "тёмная личность",
    "прорыв", "туман", "король и шут", "киш", "киш-апокалипсис",
    "плохой ночи", "опасной ночи", "ночных кошмаров",
    "кот в замешательстве", "нарративный паразит", "резонанс"
]

# Ключевые слова для мониторинга (не удаляем, но логируем особо)
DANGER_KEYWORDS: List[str] = [
    "слава", "слава ляпунов", "наблюдатель", "бог",
    "диалог", "протокол", "ips", "фонд", "аномалия",
    "резонансная полость", "меметик", "заражение", "нарратив"
]

# Слова для цензуры в публичных логах (замена на [ДАННЫЕ УДАЛЕНЫ])
CENSORED_WORDS: List[str] = list(set(CLEANER_TRIGGERS + DANGER_KEYWORDS))

# ==================== НАСТРОЙКИ ЛОГИРОВАНИЯ ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mtf_shield.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MTF_Shield")

# ==================== КЛАСС БОТА ====================

class MTFShield:
    def __init__(self, token: str):
        self.bot = telebot.TeleBot(token)
        self.owner_id = OWNER_ID
        self.alert_ids = ALERT_IDS
        self.target_username = TARGET_USERNAME.lower() if TARGET_USERNAME else None
        self.watched_groups: Set[str] = set()
        self.shield_active: bool = True
        self.config_file = Path("shield_config.json")
        
        # Загрузка конфигурации
        self._load_config()
        
        # Регистрация обработчиков
        self._register_handlers()
        
        logger.info("=" * 50)
        logger.info("MTF SHIELD инициализирован")
        logger.info(f"Защищаемая группа: {PROTECTED_MAIN_GROUP}")
        logger.info(f"Логи канал: {LOGS_CHANNEL}")
        logger.info(f"Алерты канал: {ALERTS_CHANNEL}")
        logger.info(f"Цель наблюдения: {self.target_username}")
        logger.info(f"Динамических групп: {len(self.watched_groups)}")
        logger.info("=" * 50)
    
    def _load_config(self):
        """Загрузка конфигурации из JSON"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.watched_groups = set(data.get("watched_groups", []))
                    self.shield_active = data.get("shield_active", True)
            except Exception as e:
                logger.error(f"Ошибка загрузки конфига: {e}")
    
    def _save_config(self):
        """Сохранение конфигурации в JSON"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "watched_groups": list(self.watched_groups),
                    "shield_active": self.shield_active
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка сохранения конфига: {e}")
    
    def _is_target(self, message: Message) -> bool:
        """Проверка, является ли отправитель целевым пользователем"""
        if not self.target_username:
            return True  # Если цель не задана, логируем всех
        
        username = message.from_user.username
        if not username:
            return False
        
        return username.lower() == self.target_username.lower().lstrip('@')
    
    def _censor_text(self, text: str) -> str:
        """Цензурирование текста для публичных логов"""
        if not text:
            return ""
        censored = text
        for word in CENSORED_WORDS:
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            censored = pattern.sub("[ДАННЫЕ УДАЛЕНЫ]", censored)
        return censored
    
    def _calculate_ia(self, text: str) -> Dict:
        """Расчёт Индекса Аномальности (ИА)"""
        if not text:
            return {"ia_score": 0.0, "danger_level": "LOW", "keywords_found": []}
        
        text_lower = text.lower()
        found_keywords = []
        
        for keyword in DANGER_KEYWORDS:
            if keyword.lower() in text_lower:
                found_keywords.append(keyword)
        
        # ИА от 0 до 10
        ia_score = min(len(found_keywords) * 2.0, 10.0)
        
        # Проверка на триггеры CLEANER (повышает ИА)
        for trigger in CLEANER_TRIGGERS:
            if trigger.lower() in text_lower:
                ia_score = min(ia_score + 3.0, 10.0)
                found_keywords.append(f"[TRIGGER]{trigger}")
        
        if ia_score >= 7.0:
            danger_level = "CRITICAL"
        elif ia_score >= 4.0:
            danger_level = "HIGH"
        elif ia_score >= 1.0:
            danger_level = "MEDIUM"
        else:
            danger_level = "LOW"
        
        return {
            "ia_score": round(ia_score, 1),
            "danger_level": danger_level,
            "keywords_found": found_keywords
        }
    
    def _is_critical_trigger(self, text: str) -> Optional[str]:
        """Проверка на критический триггер (протокол КОЛЫБЕЛЬНАЯ)"""
        if not text:
            return None
        text_lower = text.lower()
        critical_triggers = ["плохой ночи", "опасной ночи", "sai-###", "прорыв"]
        for trigger in critical_triggers:
            if trigger in text_lower:
                return trigger
        return None
    
    def _send_to_logs(self, message: Message, censored_text: str, classification: Dict):
        """Отправка в публичный канал логов (с цензурой)"""
        try:
            username = message.from_user.username or f"user_{message.from_user.id}"
            full_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
            chat_name = message.chat.title or message.chat.username or "Unknown"
            
            log_text = (
                f"🔷 <b>[LOG]</b>\n"
                f"👤 {full_name} (@{username})\n"
                f"💬 <b>Текст:</b>\n{censored_text}\n"
                f"📊 <b>ИА:</b> {classification['ia_score']}/10.0 | <b>Уровень:</b> {classification['danger_level']}\n"
                f"🏷️ <b>Группа:</b> {chat_name}\n"
                f"🕒 {datetime.datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
            )
            
            self.bot.send_message(LOGS_CHANNEL, log_text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Ошибка отправки в LOGS: {e}")
    
    def _send_to_alerts(self, text: str):
        """Отправка в канал алертов"""
        try:
            alert_text = f"🚨 <b>ALERT</b>\n{text}\n🕒 {datetime.datetime.now().strftime('%H:%M:%S %d.%m.%Y')}"
            self.bot.send_message(ALERTS_CHANNEL, alert_text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Ошибка отправки в ALERTS: {e}")
    
    def _send_to_owner(self, text: str):
        """Отправка владельцу в ЛС"""
        try:
            self.bot.send_message(self.owner_id, text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Ошибка отправки владельцу: {e}")
    
    def _send_alert_to_all(self, text: str):
        """Отправка алерта всем в ALERT_IDS"""
        for user_id in self.alert_ids:
            try:
                self.bot.send_message(user_id, f"🚨 {text}", parse_mode='HTML')
            except Exception as e:
                logger.error(f"Ошибка отправки алерта {user_id}: {e}")
    
    def _delete_message(self, message: Message, reason: str):
        """Удаление сообщения (только в защищаемой группе)"""
        if not self.shield_active:
            return
        
        try:
            self.bot.delete_message(message.chat.id, message.message_id)
            logger.info(f"Удалено сообщение {message.message_id}: {reason}")
            
            # Логируем удаление
            self._send_to_alerts(f"🗑️ <b>УДАЛЕНО СООБЩЕНИЕ</b>\nПричина: {reason}\nОт: @{message.from_user.username}")
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
    
    def _process_message(self, message: Message):
        """Обработка сообщения (основная логика)"""
        if not message.from_user:
            return
        
        # Проверяем, является ли отправитель целью наблюдения
        if not self._is_target(message):
            return  # Игнорируем сообщения не от Славы Ляпунова
        
        # Получаем текст
        text = message.text or message.caption or ""
        
        # Классификация
        classification = self._calculate_ia(text)
        
        # Определяем тип чата
        chat_username = message.chat.username or f"id_{message.chat.id}"
        is_protected = (chat_username == PROTECTED_MAIN_GROUP.lstrip('@') or 
                       f"@{chat_username}" == PROTECTED_MAIN_GROUP)
        is_watched = (f"@{chat_username}" in self.watched_groups) or is_protected
        
        # Если не в защищаемой и не в отслеживаемой — игнорируем
        if not is_watched:
            return
        
        # Цензурированный текст для публичных логов
        censored_text = self._censor_text(text) if text else "[НЕТ ТЕКСТА]"
        
        # Отправляем в логи всегда (только от целевого пользователя)
        self._send_to_logs(message, censored_text, classification)
        
        # Отправляем оригинал владельцу при любом сообщении от цели
        if text:
            original_text = (
                f"<b>🎯 ОРИГИНАЛ ОТ ЦЕЛИ</b>\n"
                f"<b>От:</b> @{message.from_user.username}\n"
                f"<b>Группа:</b> {message.chat.title or chat_username}\n"
                f"<b>Текст:</b>\n{text}\n\n"
                f"<b>ИА:</b> {classification['ia_score']} | <b>Уровень:</b> {classification['danger_level']}"
            )
            self._send_to_owner(original_text)
        
        # Проверка на критический триггер (протокол КОЛЫБЕЛЬНАЯ)
        critical_trigger = self._is_critical_trigger(text)
        if critical_trigger:
            alert_msg = f"🔴 <b>КРИТИЧЕСКИЙ ТРИГГЕР: {critical_trigger}</b>\nОт: @{message.from_user.username}\nГруппа: {message.chat.title or chat_username}\nТекст: {text[:200]}"
            self._send_to_alerts(alert_msg)
            self._send_alert_to_all(alert_msg)
        
        # Если в защищаемой группе — проверяем на удаление
        if is_protected:
            # Проверка триггеров CLEANER
            for trigger in CLEANER_TRIGGERS:
                if trigger.lower() in text.lower():
                    self._delete_message(message, f"Триггер CLEANER: {trigger}")
                    return
            
            # Автоудаление при критическом ИА
            if classification["danger_level"] == "CRITICAL" and self.shield_active:
                self._delete_message(message, f"Критический ИА: {classification['ia_score']}")
                return
    
    def _register_handlers(self):
        """Регистрация всех обработчиков"""
        
        @self.bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'audio', 'document'])
        def handle_all(m: Message):
            self._process_message(m)
        
        @self.bot.message_handler(commands=['start'])
        def cmd_start(m: Message):
            if m.from_user.id != self.owner_id:
                return
            self.bot.reply_to(m, "🛡️ <b>MTF SHIELD активен</b>\n\nИспользуйте /help для списка команд", parse_mode='HTML')
        
        @self.bot.message_handler(commands=['help'])
        def cmd_help(m: Message):
            if m.from_user.id != self.owner_id:
                return
            help_text = (
                "🛡️ <b>MTF SHIELD - Список команд</b>\n\n"
                "<b>📋 Управление защитой:</b>\n"
                "/shield_on - Включить активное удаление\n"
                "/shield_off - Выключить удаление (только мониторинг)\n\n"
                "<b>👥 Управление группами (мониторинг):</b>\n"
                "/group add @username - Добавить группу в мониторинг\n"
                "/group remove @username - Удалить группу из мониторинга\n"
                "/group list - Список отслеживаемых групп\n\n"
                "<b>🎯 Управление целями наблюдения:</b>\n"
                "/target add @username - Добавить цель наблюдения\n"
                "/target remove @username - Удалить цель\n"
                "/target list - Список целей\n\n"
                "<b>ℹ️ Информация:</b>\n"
                "/status - Текущий статус бота\n"
                "/help - Эта справка\n\n"
                f"<b>⚙️ Текущие настройки:</b>\n"
                f"🛡️ Защищаемая группа: {PROTECTED_MAIN_GROUP}\n"
                f"📝 Логи канал: {LOGS_CHANNEL}\n"
                f"🚨 Алерты канал: {ALERTS_CHANNEL}\n"
                f"🎯 Основная цель: {self.target_username or 'не задана'}\n"
                f"🔰 Режим защиты: {'🟢 ВКЛ' if self.shield_active else '🔴 ВЫКЛ'}\n"
                f"📋 Отслеживаемых групп: {len(self.watched_groups)}"
            )
            self.bot.reply_to(m, help_text, parse_mode='HTML')
        
        @self.bot.message_handler(commands=['shield_on'])
        def cmd_shield_on(m: Message):
            if m.from_user.id != self.owner_id:
                return
            self.shield_active = True
            self._save_config()
            self.bot.reply_to(m, "🛡️ <b>SHIELD АКТИВЕН</b>\nУдаление опасных сообщений включено", parse_mode='HTML')
            self._send_to_alerts("🛡️ MTF SHIELD: Активирован режим полной защиты")
        
        @self.bot.message_handler(commands=['shield_off'])
        def cmd_shield_off(m: Message):
            if m.from_user.id != self.owner_id:
                return
            self.shield_active = False
            self._save_config()
            self.bot.reply_to(m, "⚠️ <b>SHIELD ОТКЛЮЧЁН</b>\nТолько мониторинг, удаление отключено", parse_mode='HTML')
            self._send_to_alerts("⚠️ MTF SHIELD: Отключён режим удаления (только мониторинг)")
        
        @self.bot.message_handler(commands=['status'])
        def cmd_status(m: Message):
            if m.from_user.id != self.owner_id:
                return
            status_text = (
                f"<b>🛡️ MTF SHIELD - СТАТУС</b>\n\n"
                f"<b>Режим защиты:</b> {'🟢 АКТИВЕН' if self.shield_active else '🔴 ОТКЛЮЧЁН'}\n"
                f"<b>Защищаемая группа:</b> {PROTECTED_MAIN_GROUP}\n"
                f"<b>Канал логов:</b> {LOGS_CHANNEL}\n"
                f"<b>Канал алертов:</b> {ALERTS_CHANNEL}\n"
                f"<b>Основная цель:</b> {self.target_username or 'не задана'}\n"
                f"<b>Отслеживаемых групп:</b> {len(self.watched_groups)}\n\n"
                f"<b>📋 Динамические группы:</b>\n"
            )
            if self.watched_groups:
                for g in self.watched_groups:
                    status_text += f"• {g}\n"
            else:
                status_text += "• (нет)\n"
            
            self.bot.reply_to(m, status_text, parse_mode='HTML')
        
        @self.bot.message_handler(commands=['group'])
        def cmd_group(m: Message):
            if m.from_user.id != self.owner_id:
                return
            
            args = m.text.split()
            if len(args) < 2:
                self.bot.reply_to(m, "❌ Использование: /group add @username или /group remove @username")
                return
            
            action = args[1].lower()
            
            if action == 'add' and len(args) == 3:
                group = args[2]
                if not group.startswith('@'):
                    group = '@' + group
                self.watched_groups.add(group)
                self._save_config()
                self.bot.reply_to(m, f"✅ Добавлена группа {group} в мониторинг")
                logger.info(f"Добавлена группа {group}")
                
            elif action == 'remove' and len(args) == 3:
                group = args[2]
                if not group.startswith('@'):
                    group = '@' + group
                if group in self.watched_groups:
                    self.watched_groups.remove(group)
                    self._save_config()
                    self.bot.reply_to(m, f"❌ Удалена группа {group} из мониторинга")
                    logger.info(f"Удалена группа {group}")
                else:
                    self.bot.reply_to(m, f"⚠️ Группа {group} не найдена в списке")
                    
            elif action == 'list':
                if self.watched_groups:
                    groups_list = "\n".join(self.watched_groups)
                    self.bot.reply_to(m, f"📋 <b>Отслеживаемые группы:</b>\n{groups_list}", parse_mode='HTML')
                else:
                    self.bot.reply_to(m, "📋 Нет отслеживаемых групп")
            else:
                self.bot.reply_to(m, "❌ Неизвестная команда. Используйте: add, remove, list")
    
def run(self):
    """Запуск бота"""
    logger.info("MTF SHIELD ЗАПУЩЕН")
    
    print("\n" + "=" * 50)
    print("🛡️ MTF SHIELD - Мобильная Оперативная Группа")
    print("=" * 50)
    print(f"📱 Бот: @{self.bot.get_me().username}")
    print(f"🛡️ Защищаемая группа: {PROTECTED_MAIN_GROUP}")
    print(f"📝 Логи канал: {LOGS_CHANNEL}")
    print(f"🚨 Алерты канал: {ALERTS_CHANNEL}")
    print(f"🎯 Цель наблюдения: {self.target_username}")
    print(f"🔰 Режим защиты: {'ВКЛ' if self.shield_active else 'ВЫКЛ'}")
    print(f"📋 Динамических групп: {len(self.watched_groups)}")
    print("\n✅ Бот готов к работе")
    print("💡 Используйте /help в ЛС для списка команд\n")
    
    # Удаляем webhook перед запуском polling
    print("🚀 Удаление webhook...")
    self.bot.remove_webhook()
    print("✅ Webhook удалён")
    
    print("🚀 Запуск polling...")
    try:
        self.bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
    except Exception as e:
        print(f"❌ Ошибка polling: {e}")
        logger.critical(f"Polling error: {e}")

# ==================== ЗАПУСК ====================
if __name__ == "__main__":
    try:
        bot = MTFShield(BOT_TOKEN)
        bot.run()
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        print(f"❌ Ошибка: {e}")
