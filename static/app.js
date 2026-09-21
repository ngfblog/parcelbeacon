document.querySelectorAll(".source-picker").forEach((picker) => {
  const target = document.getElementById(picker.dataset.sourceTarget);
  if (!target) return;

  picker.addEventListener("change", () => {
    if (picker.value === "__custom__") {
      target.value = "";
      target.focus();
      return;
    }
    if (picker.value) target.value = picker.value;
  });
});
