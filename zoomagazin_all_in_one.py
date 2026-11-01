# -*- coding: utf-8 -*-
"""
 структура БД, процедуры, пользовательские функции и триггеры.

"""

import sqlite3
from typing import Optional, List, Dict, Any




def fn_price_with_discount(price: Optional[float], discount: Optional[int]) -> Optional[float]:
    """
    Скалярная функция №1: Расчёт цены зоотовара со скидкой клиента.
    Возвращает цену со скидкой (округлённую до 2 знаков) или None при некорректных данных.
    """
    if price is None or discount is None:
        return None
    if price <= 0 or discount < 0 or discount > 100:
        return None
    return round(price * (1 - discount / 100.0), 2)


def fn_client_fio(last_name: Optional[str], first_name: Optional[str], middle_name: Optional[str] = None) -> Optional[str]:
    """
    Скалярная функция №2: Форматирование ФИО покупателя в вид 'Фамилия И. О.'.
    Корректно обрабатывает отсутствие отчества (NULL / None).
    """
    if not last_name or not first_name:
        return None
    last_name = last_name.strip()
    first_name = first_name.strip()
    if not last_name or not first_name:
        return None
    result = f"{last_name} {first_name[0]}."
    if middle_name and middle_name.strip():
        result += f" {middle_name.strip()[0]}."
    return result


def fn_client_purchases(conn: sqlite3.Connection, client_id: int, date_from: str, date_to: str) -> List[Dict[str, Any]]:
    """
    Inline табличная функция  Выборка чеков клиента за выбранный период с подсчётом суммы каждого чека.
    """
    cursor = conn.cursor()
    query = """
        SELECT s.ID, s.ДатаПродажи, s.Статус,
               ROUND(SUM(si.Количество * si.Цена), 2) AS СуммаЧека
        FROM Продажи s
        JOIN ПозицииПродажи si ON si.ПродажаID = s.ID
        WHERE s.КлиентID = ? AND s.ДатаПродажи BETWEEN ? AND ?
        GROUP BY s.ID, s.ДатаПродажи, s.Статус
    """
    cursor.execute(query, (client_id, date_from, date_to))
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fn_products_by_category(conn: sqlite3.Connection, category_id: int) -> List[Dict[str, Any]]:
    """
    Inline табличная функции Выборка доступных товаров (Остаток > 0 и не в архиве) по категории.
    """
    cursor = conn.cursor()
    query = """
        SELECT ID, Название, Цена, Остаток
        FROM Товары
        WHERE КатегорияID = ? AND Остаток > 0 AND ВАрхиве = 0
    """
    cursor.execute(query, (category_id,))
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fn_stock_status_report(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """
    Многооператорная табличная функция: Контроль остатков товаров на складе.
    Считает актуальный баланс и по условиям if/elif/else определяет статус запаса.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.ID, t.Название, t.Остаток, t.МинОстаток, t.ВАрхиве,
               COALESCE((SELECT SUM(p.Количество) FROM Поставки p WHERE p.ТоварID = t.ID), 0) AS Приход,
               COALESCE((SELECT SUM(si.Количество) FROM ПозицииПродажи si WHERE si.ТоварID = t.ID), 0) AS Расход
        FROM Товары t
    """)
    report_table = []
    for row in cursor.fetchall():
        prod_id, name, current_stock, min_stock, is_archived, incoming, outgoing = row

        if is_archived == 1:
            status = "В архиве"
        elif current_stock <= 0:
            status = "Нет в наличии"
        elif current_stock <= min_stock:
            status = "Нужно заказать"
        else:
            status = "Достаточно"

        report_table.append({
            "ТоварID": prod_id,
            "Название": name,
            "ТекущийОстаток": current_stock,
            "МинПорог": min_stock,
            "ВсегоПоставлено": incoming,
            "ВсегоПродано": outgoing,
            "СтатусЗапаса": status
        })
    return report_table




def sp_add_item_to_sale(conn: sqlite3.Connection, sale_id: int, product_id: int, client_id: int, quantity: int) -> None:
    """
    Процедура добавления позиции в чек 
   
    """
    cursor = conn.cursor()
    cursor.execute("SELECT Цена FROM Товары WHERE ID = ?", (product_id,))
    prod_row = cursor.fetchone()
    cursor.execute("SELECT Скидка FROM Клиенты WHERE ID = ?", (client_id,))
    client_row = cursor.fetchone()

    if not prod_row or not client_row:
        raise ValueError("Товар или клиент не найден в базе данных!")

    final_price = fn_price_with_discount(prod_row[0], client_row[0])
    cursor.execute(
        "INSERT INTO ПозицииПродажи (ПродажаID, ТоварID, Количество, Цена) VALUES (?, ?, ?, ?)",
        (sale_id, product_id, quantity, final_price)
    )
    conn.commit()




def init_database() -> sqlite3.Connection:
    # Создаём БД в оперативной памяти
    conn = sqlite3.connect(":memory:")

    # Регистрируем скалярные функции в SQLite, чтобы вызывать их прямо внутри SQL-запросов
    conn.create_function("fn_ЦенаСоСкидкой", 2, fn_price_with_discount)
    conn.create_function("fn_ФИОКлиента", 3, fn_client_fio)

    cur = conn.cursor()

    #  Создание таблиц базы данных «Зоомагазин» и таблицы аудита
    cur.executescript("""
        CREATE TABLE Категории (
            ID INTEGER PRIMARY KEY,
            Название TEXT NOT NULL
        );

        CREATE TABLE Товары (
            ID INTEGER PRIMARY KEY,
            Название TEXT NOT NULL,
            КатегорияID INTEGER,
            Цена REAL NOT NULL,
            Остаток INTEGER NOT NULL,
            МинОстаток INTEGER NOT NULL,
            ВАрхиве INTEGER DEFAULT 0,
            FOREIGN KEY (КатегорияID) REFERENCES Категории(ID)
        );

        CREATE TABLE Клиенты (
            ID INTEGER PRIMARY KEY,
            Фамилия TEXT NOT NULL,
            Имя TEXT NOT NULL,
            Отчество TEXT,
            Телефон TEXT,
            Скидка INTEGER DEFAULT 0
        );

        CREATE TABLE Продажи (
            ID INTEGER PRIMARY KEY,
            КлиентID INTEGER,
            ДатаПродажи TEXT,
            Статус TEXT,
            FOREIGN KEY (КлиентID) REFERENCES Клиенты(ID)
        );

        CREATE TABLE ПозицииПродажи (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            ПродажаID INTEGER,
            ТоварID INTEGER,
            Количество INTEGER,
            Цена REAL,
            FOREIGN KEY (ПродажаID) REFERENCES Продажи(ID),
            FOREIGN KEY (ТоварID) REFERENCES Товары(ID)
        );

        CREATE TABLE Поставки (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            ТоварID INTEGER,
            ДатаПоставки TEXT,
            Количество INTEGER,
            FOREIGN KEY (ТоварID) REFERENCES Товары(ID)
        );

        -- Таблица аудита изменений (Этап 4, Шаг 2)
        CREATE TABLE АудитИзменений (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Таблица TEXT NOT NULL,
            Операция TEXT NOT NULL,
            Данные TEXT NOT NULL,
            Пользователь TEXT DEFAULT 'student_user',
            ДатаИзменения TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- Представление для демонстрации триггера INSTEAD OF DELETE в SQLite (Этап 4, Шаг 5)
        CREATE VIEW vw_Товары AS
        SELECT ID, Название, КатегорияID, Цена, Остаток, МинОстаток, ВАрхиве
        FROM Товары;
    """)

    # Создание AFTER-триггеров аудита (Этап 4, Шаг 3)
    cur.executescript("""
        CREATE TRIGGER trg_Товары_Audit_Insert
        AFTER INSERT ON Товары
        BEGIN
            INSERT INTO АудитИзменений (Таблица, Операция, Данные)
            VALUES (
                'Товары',
                'INSERT',
                'Добавлен товар: ' || NEW.Название || ', цена: ' || NEW.Цена || ', остаток: ' || NEW.Остаток
            );
        END;

        CREATE TRIGGER trg_Товары_Audit_Update
        AFTER UPDATE ON Товары
        BEGIN
            INSERT INTO АудитИзменений (Таблица, Операция, Данные)
            VALUES (
                'Товары',
                'UPDATE',
                'Товар ID=' || OLD.ID || ' (' || OLD.Название || '): старая цена=' || OLD.Цена
                || ' -> новая цена=' || NEW.Цена
                || ', старый остаток=' || OLD.Остаток || ' -> новый остаток=' || NEW.Остаток
                || ', архив=' || NEW.ВАрхиве
            );
        END;

        CREATE TRIGGER trg_Продажи_Audit_Insert
        AFTER INSERT ON Продажи
        BEGIN
            INSERT INTO АудитИзменений (Таблица, Операция, Данные)
            VALUES (
                'Продажи',
                'INSERT',
                'Создан чек ID=' || NEW.ID || ', клиент ID=' || NEW.КлиентID || ', статус: ' || NEW.Статус
            );
        END;

        CREATE TRIGGER trg_Продажи_Audit_Update
        AFTER UPDATE ON Продажи
        BEGIN
            INSERT INTO АудитИзменений (Таблица, Операция, Данные)
            VALUES (
                'Продажи',
                'UPDATE',
                'Чек ID=' || OLD.ID || ': старый статус=' || OLD.Статус || ' -> новый статус=' || NEW.Статус
            );
        END;
    """)

    # Создание триггеров контроля бизнес-правил и списания остатков
    cur.executescript("""
        CREATE TRIGGER trg_ПозицииПродажи_БизнесПравила
        BEFORE INSERT ON ПозицииПродажи
        BEGIN
            -- Правило 1: товар не должен быть в архиве
            SELECT RAISE(ABORT, 'Ошибка 50011: Нельзя добавить в чек товар из архива!')
            WHERE (SELECT ВАрхиве FROM Товары WHERE ID = NEW.ТоварID) = 1;

            -- Правило 2: на складе должно хватать остатка
            SELECT RAISE(ABORT, 'Ошибка 50012: Недостаточно товара на складе для продажи!')
            WHERE (SELECT Остаток FROM Товары WHERE ID = NEW.ТоварID) < NEW.Количество;

            -- Правило 3: не более 15 позиций в одном чеке
            SELECT RAISE(ABORT, 'Ошибка 50010: В один чек нельзя добавить более 15 позиций!')
            WHERE (SELECT COUNT(*) FROM ПозицииПродажи WHERE ПродажаID = NEW.ПродажаID) >= 15;
        END;

        CREATE TRIGGER trg_ПозицииПродажи_СписаниеОстатка
        AFTER INSERT ON ПозицииПродажи
        BEGIN
            UPDATE Товары
            SET Остаток = Остаток - NEW.Количество
            WHERE ID = NEW.ТоварID;
        END;
    """)

    #  Создание триггера INSTEAD OF DELETE для  удаления товара в архив 
    cur.executescript("""
        CREATE TRIGGER trg_Товары_InsteadOfDelete
        INSTEAD OF DELETE ON vw_Товары
        BEGIN
            UPDATE Товары
            SET ВАрхиве = 1
            WHERE ID = OLD.ID;

            INSERT INTO АудитИзменений (Таблица, Операция, Данные)
            VALUES (
                'Товары',
                'SOFT_DELETE',
                'Товар ID=' || OLD.ID || ' (' || OLD.Название || ') переведён в архив вместо физического удаления'
            );
        END;
    """)

    # 5. Заполнение базы начальными тестовыми данными
    cur.executescript("""
        INSERT INTO Категории VALUES
            (1, 'Корма для кошек'),
            (2, 'Корма для собак'),
            (3, 'Игрушки и аксессуары');

        INSERT INTO Товары (ID, Название, КатегорияID, Цена, Остаток, МинОстаток, ВАрхиве) VALUES
            (1, 'Сухой корм Royal Canin 2 кг', 1, 1800.00, 15, 5, 0),
            (2, 'Влажный корм Purina Pro Plan 85 г', 1, 120.00, 20, 10, 0),
            (3, 'Корм для собак Grandorf 3 кг', 2, 2500.00, 0, 3, 0),
            (4, 'Когтеточка-столбик', 3, 1500.00, 6, 2, 0);

        INSERT INTO Клиенты VALUES
            (1, 'Смирнов', 'Алексей', 'Игоревич', '+79001112233', 10),
            (2, 'Кузнецова', 'Мария', NULL, '+79004445566', 5);

        INSERT INTO Поставки (ТоварID, ДатаПоставки, Количество) VALUES
            (1, '2026-03-01', 15),
            (2, '2026-03-01', 20),
            (4, '2026-03-01', 6);

        INSERT INTO Продажи VALUES
            (1, 1, '2026-03-10', 'Оплачен'),
            (2, 1, '2026-03-15', 'Оплачен');
    """)
    conn.commit()
    return conn



def main():
    print("=" * 78)
    print("ЗАПУСК ПРОЕКТА «ЗООМАГАЗИН» (ЭТАПЫ 3 И 4: ФУНКЦИИ, ПРОЦЕДУРЫ И ТРИГГЕРЫ)")
    print("=" * 78)

    conn = init_database()
    cur = conn.cursor()

    #  ПРОВЕРКА ПОЛЬЗОВАТЕЛЬСКИХ ФУНКЦИЙ 
  
    print("\n--- [ЭТАП 3] 1. Скалярные функции в SQL-запросе (SELECT / WHERE / ORDER BY) ---")
    cur.execute("""
        SELECT Название, Цена, fn_ЦенаСоСкидкой(Цена, 10) AS ЦенаСоСкидкой10
        FROM Товары
        WHERE fn_ЦенаСоСкидкой(Цена, 10) > 150
        ORDER BY fn_ЦенаСоСкидкой(Цена, 10) DESC
    """)
    for row in cur.fetchall():
        print(f"  Товар: {row[0]} | Базовая цена: {row[1]} руб. | Со скидкой 10%: {row[2]} руб.")

    print("\n--- [ЭТАП 3] 2. Форматирование ФИО клиентов (fn_ФИОКлиента) ---")
    cur.execute("SELECT ID, fn_ФИОКлиента(Фамилия, Имя, Отчество) AS КраткоеФИО, Скидка FROM Клиенты")
    for row in cur.fetchall():
        print(f"  Клиент ID={row[0]}: {row[1]} (скидка {row[2]}%)")

    print("\n--- [ЭТАП 3] 3. Проверка граничных значений и NULL для скалярных функций ---")
    print("  fn_price_with_discount(500, 10)  ->", fn_price_with_discount(500, 10))
    print("  fn_price_with_discount(None, 10) ->", fn_price_with_discount(None, 10))
    print("  fn_price_with_discount(500, -5)  ->", fn_price_with_discount(500, -5))
    print("  fn_client_fio('Кузнецова', 'Мария', None) ->", fn_client_fio("Кузнецова", "Мария", None))

    print("\n--- [ЭТАП 2+3+4] 4. Добавление товаров в чеки через процедуру sp_add_item_to_sale ---")
    sp_add_item_to_sale(conn, sale_id=1, product_id=1, client_id=1, quantity=1)
    sp_add_item_to_sale(conn, sale_id=1, product_id=2, client_id=1, quantity=12)
    sp_add_item_to_sale(conn, sale_id=2, product_id=4, client_id=1, quantity=1)
    print("  Позиции успешно добавлены в чеки №1 и №2 (цены посчитаны со скидкой, остатки списаны триггером).")

    print("\n--- [ЭТАП 3] 5. Inline табличная функция: Покупки клиента ID=1 за март 2026 ---")
    for item in fn_client_purchases(conn, 1, "2026-03-01", "2026-03-31"):
        print(" ", item)

    print("\n--- [ЭТАП 3] 6. Inline табличная функция: Доступные товары категории 1 (Корма для кошек) ---")
    for item in fn_products_by_category(conn, 1):
        print(" ", item)

    print("\n--- [ЭТАП 3] 7. Многооператорная табличная функция: Контроль остатков на складе ---")
    for item in fn_stock_status_report(conn):
        print(f"  ID={item['ТоварID']} | {item['Название']} | Остаток: {item['ТекущийОстаток']} (мин: {item['МинПорог']}) | Статус: {item['СтатусЗапаса']}")

     
    # ПРОВЕРКА ТРИГГЕРОВ И ЗАЩИТЫ БИЗНЕС-ПРАВИЛ 

    print("\n--- [ЭТАП 4] 8. Тест триггера аудита UPDATE цены товара ---")
    cur.execute("UPDATE Товары SET Цена = 1950.00 WHERE ID = 1")
    conn.commit()
    print("  Цена товара ID=1 обновлена с 1800.0 до 1950.0 руб. (записано в АудитИзменений).")

    print("\n--- [ЭТАП 4] 9. Тест контроля остатка: попытка продать 50 шт. при остатке 5 шт. ---")
    try:
        sp_add_item_to_sale(conn, sale_id=2, product_id=4, client_id=1, quantity=50)
    except sqlite3.IntegrityError as e:
        conn.rollback()
        print("  [УСПЕШНО ЗАБЛОКИРОВАНО ТРИГГЕРОМ]:", e)

    print("\n--- [ЭТАП 4] 10. Тест INSTEAD OF DELETE: мягкое удаление товара в архив ---")
    cur.execute("DELETE FROM vw_Товары WHERE ID = 4")
    conn.commit()
    cur.execute("SELECT ID, Название, Остаток, ВАрхиве FROM Товары WHERE ID = 4")
    prod4 = cur.fetchone()
    print(f"  Товар после DELETE остаётся в БД: ID={prod4[0]}, «{prod4[1]}», остаток={prod4[2]}, ВАрхиве={prod4[3]}")

    print("\n--- [ЭТАП 4] 11. Тест запрета продажи архивного товара ---")
    try:
        sp_add_item_to_sale(conn, sale_id=2, product_id=4, client_id=1, quantity=1)
    except sqlite3.IntegrityError as e:
        conn.rollback()
        print("  [УСПЕШНО ЗАБЛОКИРОВАНО ТРИГГЕРОМ]:", e)

    print("\n--- [ЭТАП 4] 12. Тест лимита 15 позиций в одном чеке ---")
    try:
        # В чеке №1 уже есть 2 позиции, пробуем добавить ещё 14 (на 16-й сработает триггер)
        for _ in range(14):
            cur.execute("INSERT INTO ПозицииПродажи (ПродажаID, ТоварID, Количество, Цена) VALUES (1, 1, 1, 1620.00)")
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.rollback()
        print("  [УСПЕШНО ЗАБЛОКИРОВАНО ТРИГГЕРОМ]:", e)

    print("\n--- [ЭТАП 4] 13. Журнал таблицы АудитИзменений ---")
    cur.execute("SELECT ID, Таблица, Операция, Данные, ДатаИзменения FROM АудитИзменений ORDER BY ID")
    for row in cur.fetchall():
        print(f"  [{row[0]:02d}] {row[4]} | {row[1]:7s} | {row[2]:11s} | {row[3]}")

    conn.close()
    print("\n" + "=" * 78)
    print("Все тесты этапов 3 и 4 успешно выполнены!")
    print("=" * 78)


if __name__ == "__main__":
    main()