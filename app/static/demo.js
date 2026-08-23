(() => {
  const country = document.querySelector("#phone-country");
  const phone = document.querySelector("input[name='phone_number']");
  if (!country || !phone) return;

  country.addEventListener("change", () => {
    if (!phone.value || /^\+(34|52)/.test(phone.value)) phone.value = country.value;
  });
})();
