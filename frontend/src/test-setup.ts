import "@testing-library/jest-dom";

// jsdom doesn't implement scrollIntoView; components call it on form open.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
