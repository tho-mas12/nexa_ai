const loginForm =
document.getElementById("loginForm");

const loginBtn =
document.getElementById("loginBtn");

const logoSpin =
document.getElementById("logoSpin");

/* ==========================
   BUBBLE EXPLOSION
========================== */

function createBubbleExplosion() {

  const totalBubbles = 150;

  for(let i = 0; i < totalBubbles; i++){

    const bubble =
    document.createElement("div");

    bubble.classList.add(
      "blast-bubble"
    );

    /* Random size */
    const size =
    Math.random() * 50 + 10;

    bubble.style.width =
    `${size}px`;

    bubble.style.height =
    `${size}px`;

    /* Start from center */
    bubble.style.left =
    "50%";

    bubble.style.top =
    "50%";

    /* Random pastel colors */
    const colors = [
      "rgba(168,85,247,.25)",
      "rgba(236,72,153,.25)",
      "rgba(96,165,250,.25)",
      "rgba(255,210,80,.22)",
      "rgba(255,255,255,.25)"
    ];

    bubble.style.background =
    colors[
      Math.floor(
        Math.random() *
        colors.length
      )
    ];

    document.body.appendChild(
      bubble
    );

    /* SAFE movement */
    const x =
    (Math.random() - 0.5)
    * window.innerWidth;

    const y =
    (Math.random() - 0.5)
    * window.innerHeight;

    requestAnimationFrame(() => {

      bubble.style.transform =
      `translate(${x}px,
      ${y}px) scale(1.8)`;

      bubble.style.opacity =
      "0";
    });

    setTimeout(() => {
      bubble.remove();
    }, 2800);
  }
}

/* ==========================
   LOGIN
========================== */

loginForm.addEventListener("submit", async function(e) {
  e.preventDefault();

  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;

  loginBtn.disabled = true;
  loginBtn.innerHTML = "Logging in...";
  loginBtn.style.opacity = "0.8";

  /* Spin logo */
  logoSpin.classList.add("spinning");

  /* Explosion */
  createBubbleExplosion();

  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || 'Login failed');
    }

    // Save token and email
    localStorage.setItem('nexa_token', data.token);
    localStorage.setItem('nexa_email', data.email);

    setTimeout(() => {
      loginBtn.innerHTML = "Welcome to NeXa ✨";
    }, 1500);

    setTimeout(() => {
      window.location.href = "main.html";
    }, 2800);

  } catch (error) {
    logoSpin.classList.remove("spinning");
    loginBtn.disabled = false;
    loginBtn.innerHTML = "Log in to NeXa";
    loginBtn.style.opacity = "1";
    alert("Login Error: " + error.message);
  }
});