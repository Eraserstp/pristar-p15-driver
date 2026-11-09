# Pristar P15 — драйвер CUPS для Linux

[English](README.md) | **Русский**

Драйвер CUPS для Bluetooth-принтера этикеток **Pristar P15** (он же Marklife
P15 и совместимые клоны). После установки принтер появляется как обычная
очередь CUPS и доступен в диалоге печати любого приложения.

Проверено на Linux Mint 22.3 (CUPS 2.4.7, cups-filters 2.0), этикетки
40 × 12 мм с зазором.

## Возможности

- Печать из любого приложения: LibreOffice, Chromium, GTK/Qt-программы,
  `lp`/`lpr`.
- Размеры этикеток 22 × 12 … 50 × 15 мм (12–15 мм по ширине головки).
- Опции печати: плотность (1–3), тип ленты gap/continuous, дизеринг,
  длина подачи.
- Автоматическое создание очереди CUPS при установке, если принтер уже
  известен BlueZ.
- Маленький helper с `cap_net_raw` вместо root-демона.
- Никакого фирменного приложения, облака и обязательного сопряжения.

## Требования

- Linux с CUPS 2.4 и cups-filters (Linux Mint 21/22, Ubuntu 22.04/24.04).
- Bluetooth LE адаптер.
- Принтер включён, заряжен и не подключён к телефону.
- Python 3 с `python3-dbus`, `python3-gi`, `python3-pil` (ставятся как
  зависимости пакета).

## Установка

Собрать пакет из репозитория:

```bash
make deb
sudo dpkg -i ../pristar-p15-driver_*.deb
sudo apt -f install
```

Или установить готовый `.deb`:

```bash
sudo dpkg -i pristar-p15-driver_0.1.0_amd64.deb
sudo apt -f install
```

Пакет устанавливает фильтр, бэкенд, PPD и helper с capability, затем
запускает `pristar-p15-setup --auto`. Если принтер уже виден BlueZ,
создаётся очередь `Pristar-P15`. Принтером по умолчанию очередь **не**
назначается.

Если при установке принтер ещё не был известен, включите его и выполните:

```bash
sudo pristar-p15-setup
```

Скрипт найдёт устройство с именем `P15*` (или `P12*`, `P7*`, …), запишет
`/etc/pristar-p15.conf` и создаст очередь.

## Использование

```bash
lp -d Pristar-P15 документ.pdf
lp -d Pristar-P15 -o media=12x40mmRotated.Fullbleed -o P15Density=3 фото.png
lpstat -p Pristar-P15
```

В диалоге печати выберите **Pristar-P15** и размер этикетки (по умолчанию
40 × 12 мм). Работают все стандартные средства CUPS: `lp`, `lpr`,
`system-config-printer`, диалоги печати GNOME/KDE и приложений.

### Размеры этикеток

| Опция PPD | Размер |
|---|---|
| `12x22mmRotated.Fullbleed` | 22 × 12 мм |
| `14x22mmRotated.Fullbleed` | 22 × 14 мм |
| `15x26mmRotated.Fullbleed` | 26 × 15 мм |
| `12x30mmRotated.Fullbleed` | 30 × 12 мм |
| `14x30mmRotated.Fullbleed` | 30 × 14 мм |
| `15x30mmRotated.Fullbleed` | 30 × 15 мм |
| `12x40mmRotated.Fullbleed` | 40 × 12 мм (по умолчанию) |
| `14x40mmRotated.Fullbleed` | 40 × 14 мм |
| `15x40mmRotated.Fullbleed` | 40 × 15 мм |
| `15x50mmRotated.Fullbleed` | 50 × 15 мм |

Имя построено по стандарту Adobe PPD («короткая сторона × длинная сторона,
повёрнуто»); в интерфейсе показывается привычное «40x12 mm».

### Опции печати

| Опция | Значения | По умолчанию |
|---|---|---|
| `P15Density` | 1 (светло), 2, 3 (темно) | 2 |
| `P15PaperType` | `Gap`, `Continuous` | `Gap` |
| `P15Dither` | `Threshold` (текст), `FS` (фото), `None` | `Threshold` |
| `P15FeedDots` | 100, 150, 200 | 100 |

Для 1-битного растра (обычный путь CUPS) дизеринг не применяется — края
только обрезаются на величину механического допуска, поэтому вокруг текста
нет лишних точек.

## Как это устроено

```
приложение → CUPS → pdftopdf → pdftoraster
           → фильтр p15-raster  (CUPS raster → команды L11)
           → бэкенд p15         (URI p15:///<MAC>)
           → p15-leconnect (cap_net_raw) → LE-соединение
           → BlueZ D-Bus GATT → принтер
```

- **p15-leconnect** создаёт LE-соединение на уровне HCI. Принтер не выставляет
  флаг «BR/EDR Not Supported», поэтому BlueZ иначе выбирает BR/EDR и GATT
  не появляется.
- **p15-raster** разбирает CUPS raster (RaS3, 1 bpp K), поворачивает страницу
  на 270°, применяет измеренные поля головки и формирует последовательность
  L11.
- **p15** отправляет поток по GATT с кредитным управлением (пакеты 95 байт,
  тик 30 мс, восстановление через 1 с) и ждёт `OK` (`0x4F 0x4B`) от принтера.

Заметки по протоколу: [docs/ANALYSIS.md](docs/ANALYSIS.md),
[REVERSE_ENGINEERING.md](https://github.com/tomLadder/thermoprint/blob/main/REVERSE_ENGINEERING.md).

## Благодарности

Большое спасибо **[tomLadder](https://github.com/tomLadder)** за проект
[thermoprint](https://github.com/tomLadder/thermoprint) и документ
[REVERSE_ENGINEERING.md](https://github.com/tomLadder/thermoprint/blob/main/REVERSE_ENGINEERING.md),
в котором описаны протокол L11, BLE flow control и особенности P15. Этот
драйвер — независимая реализация для CUPS, построенная на этих знаниях.
thermoprint распространяется под MIT.

Спасибо также сообществу Marklife/Pristar за тестирование и отчёты.

## Диагностика

**Принтер не найден / «printer GATT not available»**

- Принтер включён, заряжен, находится рядом и не подключён к телефону.
- Некоторые контроллеры Bluetooth иногда отвечают `Command Disallowed` после
  LE-отключения. Helper отменяет зависшее создание и повторяет попытку; если
  не помогает — один раз перезапустите адаптер:

  ```bash
  bluetoothctl power off
  sleep 2
  bluetoothctl power on
  ```

- Проверьте capability helper'а:

  ```bash
  getcap /usr/lib/pristar-p15/p15-leconnect
  # ожидается: cap_net_raw=ep
  ```

**Задание завершается, но печати нет**

- Проверьте `lpstat -p Pristar-P15 -l` и `lpstat -W completed -o`.
- Логи CUPS:

  ```bash
  sudo journalctl -u cups -f
  sudo tail -f /var/log/cups/error_log
  ```

  Включите `LogLevel debug` в `/etc/cups/cupsd.conf`, чтобы видеть сообщения
  фильтра/бэкенда, и перезапустите CUPS.

**Смещение или обрезка у края**

Это механический допуск головки. Поля задаются в `/etc/pristar-p15.conf`:

```ini
[device]
mac = <MAC>
helper = /usr/lib/pristar-p15/p15-leconnect
head_margin = 2   ; пустые точки с каждой стороны по ширине головки
feed_start = 2    ; пустые точки в начале этикетки
feed_end = 6      ; пустые точки в конце этикетки
x_shift = 0       ; сдвиг поперёк головки, в точках
```

**Проверка без CUPS**

```bash
sudo /usr/lib/pristar-p15/p15-leconnect <MAC>
printf '' | /usr/lib/cups/backend/p15     # только обнаружение устройства
```

## Разработка

```bash
make test          # юнит-тесты: protocol, raster, image
make deb           # собрать Debian-пакет
make install       # установить собранный пакет
```

Ручной прогон фильтра:

```bash
PPD=ppd/pristar-p15.ppd /usr/lib/cups/filter/pdftoraster \
    1 user test 1 "Resolution=203dpi" label.pdf > /tmp/label.rast
PRISTAR_P15_LIB=src python3 src/filter/p15-raster \
    1 user test 1 "P15Density=2" /tmp/label.rast > /tmp/job.bin
```

Структура проекта:

```
src/pristar_p15/      протокол, разбор raster, обработка изображения, BLE
src/filter/p15-raster фильтр CUPS
src/backend/p15       бэкенд CUPS
src/helper/           p15-leconnect (C, cap_net_raw)
src/cli/              pristar-p15-setup
ppd/                  генератор PPD и готовый PPD
debian/               упаковка Debian
tests/                юнит-тесты
tools/                скрипты проверки и диагностики на железе
```

## Ограничения

- Только Bluetooth LE (у P15 нет USB).
- Один job за раз (BLE-соединение сериализуется lock-файлом).
- CUPS 2.4 / PPD-драйверы. В CUPS 3.x PPD будет удалён — планируется вариант
  на PAPPL/IPP Everywhere.
- Прошивка клона может не присылать подтверждение печати. Если все данные
  отправлены, задание считается успешным, чтобы не было повторной печати.

## Лицензия

MIT — см. [LICENSE](LICENSE).
