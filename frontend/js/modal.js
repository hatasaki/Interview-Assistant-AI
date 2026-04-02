/**
 * Modal for interview detail registration.
 */

const overlay = document.getElementById("modal-overlay");
const form = document.getElementById("interview-form");
const btnRegister = document.getElementById("btn-register");
const btnCancel = document.getElementById("btn-cancel-modal");

let _onRegister = null;

export function initModal(onRegister) {
  _onRegister = onRegister;

  btnRegister.addEventListener("click", () => {
    overlay.hidden = false;
  });

  btnCancel.addEventListener("click", () => {
    overlay.hidden = true;
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = {
      intervieweeName: document.getElementById("field-name").value.trim(),
      intervieweeAffiliation: document
        .getElementById("field-affiliation")
        .value.trim(),
      relatedInfo: document.getElementById("field-related-info").value.trim(),
      durationMinutes: parseInt(
        document.getElementById("field-duration").value,
        10
      ),
      goal: document.getElementById("field-goal").value.trim(),
    };
    overlay.hidden = true;
    if (_onRegister) _onRegister(data);
  });
}
