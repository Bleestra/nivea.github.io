const start = document.querySelector("#start");
const game = document.querySelector("#game");
const finish = document.querySelector("#finish");

const bottle = document.querySelector("#start img:nth-child(3)");
const hand = document.querySelector("#start img:nth-child(2)");

const bottle2 = document.querySelector("#game img:nth-child(3)");
const pena = document.querySelector("#game img:nth-child(2)");
const bck2 = document.querySelector("#game img:nth-child(1)");
const bck3 = document.querySelector("#game img:nth-child(4)");

const canvas = document.getElementById("penaCanvas");
const ctx = canvas.getContext("2d");

// Устанавливаем размеры canvas на основе размера pena
const updateCanvasSize = () => {
  canvas.width = pena.offsetWidth;
  canvas.height = pena.offsetHeight;
};

pena.onload = () => {
  updateCanvasSize();
  ctx.drawImage(pena, 0, 0, canvas.width, canvas.height);
};

document.addEventListener("click", function () {
  // Установка начального состояния
  hand.style.transition =
    "transform 1s, opacity 1s, visibility 2.2s, left 1.5s, top 1s, width 1s, height 1s";
  hand.style.opacity = "0";
  bottle.style.transition =
    "transform 1s, opacity 1s, visibility 2.2s, left 1.5s, top 1s, width 1s, height 1s";
  bottle.style.transform = "rotate(-30deg)";
  setTimeout(() => {
    bottle.style.transition =
      "transform 1s, opacity 1s, visibility 2.2s, left 1.5s, top 1s, width 1s, height 1s";
    bottle.style.transform = "rotate(30deg)";
    setTimeout(() => {
      bottle.style.transition =
        "transform 1s, opacity 1s, visibility 2.2s, left 1.5s, top 1s, width 1s, height 1s";
      bottle.style.transform = "rotate(0deg)";
      setTimeout(() => {
        start.style.transition =
          "transform 1s, opacity 1s, visibility 2.2s, left 1.5s, top 1s, width 1s, height 1s";
        start.style.visibility = "hidden";
        game.style.transition =
          "transform 1s, opacity 1s, visibility 2.2s, left 1.5s, top 1s, width 1s, height 1s";
        game.style.visibility = "visible";
        setTimeout(() => {
          bottle2.style.transition =
            "transform 1s, opacity 1s, visibility 2.2s, left 1s, top 1s, width 1s, height 1s";
          bottle2.style.left = "123px";
          bottle2.style.top = "215px";
          setTimeout(() => {
            bottle2.style.transition =
              "transform 1s, opacity 1s, visibility 2.2s, left 1s, top 1s, width 1s, height 1s";
            pena.style.display = "block"; // Прячем оригинальный pena
            bck3.style.opacity = "1";
            bck2.style.visibility = "hidden";
            canvas.style.display = "block"; // Показываем canvas

            // Устанавливаем позицию canvas
            const rect = pena.getBoundingClientRect();
            canvas.style.position = "absolute";
            canvas.style.left = `${rect.left}px`;
            canvas.style.top = `${rect.top}px`;

            // Обновляем размер и рисуем изображение на canvas
            updateCanvasSize();
            ctx.drawImage(pena, 0, 0, canvas.width, canvas.height);

            setTimeout(() => {
              bottle2.style.transition =
                "transform 1s, opacity 1s, visibility 2.2s, left 1s, top 1s, width 1s, height 1s";
              bottle2.style.opacity = "0";
              document.body.style.cursor = 'url("cursor.png"), auto';
            }, 100);
          }, 1000);
        }, 1000);
      }, 1000);
    }, 1000);
  }, 1000);
});

let totalErasedArea = 0; // Общая площадь стертых участков
const eraseRadius = 20; // Радиус стирания
let isDrawing = false; // Флаг для отслеживания рисования/стирания

const startErasing = (x, y) => {
  ctx.globalCompositeOperation = "destination-out";
  ctx.beginPath();
  ctx.arc(x, y, eraseRadius, 0, Math.PI * 2, false);
  ctx.fill();

  // Увеличиваем площадь стертых участков
  const erasedArea = Math.PI * eraseRadius * eraseRadius; // Площадь круга
  totalErasedArea += erasedArea;

  // Проверяем, если стерта большая часть канваса
  const totalCanvasArea = (canvas.width * canvas.height) * 20;
  if (totalErasedArea >= totalCanvasArea) {
    console.log("Всё стерто!");
    canvas.removeEventListener("mousemove", handleMouseMove);
    canvas.removeEventListener("mousedown", handleMouseDown);
    canvas.removeEventListener("mouseup", handleMouseUp);
    canvas.removeEventListener("touchmove", handleTouchMove);
    canvas.removeEventListener("touchstart", handleTouchStart);
    canvas.removeEventListener("touchend", handleTouchEnd);

    finish.style.transition =
      "transform 1s, opacity 1s, visibility 2.2s, left 3s, top 1s, width 1s, height 1s";
    finish.style.visibility = "visible";
    finish.style.left = "0px";
    document.getElementById("click_area").href = yandexHTML5BannerApi.getClickURLNum(1);
  }
};

const handleMouseDown = (e) => {
  isDrawing = true;
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  startErasing(x, y);
};

const handleMouseMove = (e) => {
  if (!isDrawing) return;
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  startErasing(x, y);
};

const handleMouseUp = () => {
  isDrawing = false;
};

const handleTouchStart = (e) => {
  isDrawing = true;
  const rect = canvas.getBoundingClientRect();
  const x = e.touches[0].clientX - rect.left;
  const y = e.touches[0].clientY - rect.top;
  startErasing(x, y);
};

const handleTouchMove = (e) => {
  if (!isDrawing) return;
  const rect = canvas.getBoundingClientRect();
  const x = e.touches[0].clientX - rect.left;
  const y = e.touches[0].clientY - rect.top;
  startErasing(x, y);
};

const handleTouchEnd = () => {
  isDrawing = false;
};

// Добавляем события для ПК
canvas.addEventListener("mousedown", handleMouseDown);
canvas.addEventListener("mousemove", handleMouseMove);
canvas.addEventListener("mouseup", handleMouseUp);

// Добавляем события для мобильных устройств
canvas.addEventListener("touchstart", handleTouchStart);
canvas.addEventListener("touchmove", handleTouchMove);
canvas.addEventListener("touchend", handleTouchEnd);
