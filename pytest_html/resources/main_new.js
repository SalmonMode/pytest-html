/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this file,
 * You can obtain one at http://mozilla.org/MPL/2.0/. */


resultsTree = {results_tree}

projectName = "{project_name}"


shown_states = {
    "passed": true,
    "skipped": true,
    "failed": true,
    "error": true,
    "xfailed": true,
    "xpassed": true,
}


function toggleShownState() {
    var outcome = null
    for (let o of Object.keys(shown_states)) {
        if (this.classList.contains(o)) {
            outcome = o;
            break
        }
    }
    shown_states[outcome] = !shown_states[outcome]
    updateOutcomeCountVisibility(outcome)
    updateTestVisibility()

}

function updateOutcomeCountVisibility(outcome=null) {
    var outcomes = outcome ? [outcome] : Object.keys(shown_states);

    for (let k of outcomes) {
        for (let el of document.querySelectorAll(`.${k}`)) {
            if (shown_states[k]) {
                el.classList.add("shown")
            } else {
                el.classList.remove("shown")
            }
        }
    }
}

function updateTestVisibility() {
    // var outcomes = outcome ? [outcome] : Object.keys(shown_states);

    var true_keys = [];
    var false_keys = [];

    for (let k of Object.keys(shown_states)) {
        if (shown_states[k]) {
            true_keys.push(k);
        } else {
            false_keys.push(k)
        }
    }

    var selectorList = [];
    var filter = "";

    for (let k of true_keys){
        filter += `:not(.${k})`;
    }

    for (let k of false_keys) {
        selectorList.push(`li.${k}${filter}`);
    }
    var hideSelector = selectorList.join();

    if (hideSelector) {
        for (let el of document.querySelectorAll(hideSelector)) {
            el.classList.remove("shown");
        }
    }

    showSelectorList = [];
    for (let k of true_keys){
        showSelectorList.push(`li.${k}`);
    }

    showSelector = showSelectorList.join();

    if (showSelector) {
        for (let el of document.querySelectorAll(showSelector)) {
            el.classList.add("shown")
        }
    }

    // for (let k of outcomes) {
    //     for (let el of document.querySelectorAll(`.test-result.${k}`)) {
    //         if (shown_states[k]) {
    //             el.classList.add("shown")
    //         } else {
    //             el.classList.remove("shown")
    //         }
    //     }
    // }
}


function showImageFromPreview() {
    var imageContainer = document.createElement("div");
    imageContainer.setAttribute("class", `image-container-wrapper`);
    imageContainer.innerHTML = `
        <div class="image-container">
            <div class="backdrop"></div>
            <div class="image-close-button"></div>
            ${this.innerHTML}
        </div>
    `
    imageContainer.querySelector(".image-close-button").addEventListener('click', closeImage, false);
    document.body.appendChild(imageContainer);
}

function closeImage() {
    document.body.removeChild(document.body.querySelector(".image-container-wrapper"));
}


function init () {
    prepareResultsHeaders();
    updateOutcomeCountVisibility();
    updateTestVisibility();

};


function toggleOpenClass() {
    this.parentNode.parentNode.classList.toggle("active");
}

function toggleOpenTrigger() {
    toggleOpen(this);
}

function toggleOpen(nodeLink) {
    if (!nodeLink.parentNode.data.children.length && !nodeLink.parentNode.data.test_results.length) {
        // nothing to show or hide
        return;
    }
    if (nodeLink.classList.contains("active")) {
        // already active so remove children after hiding them
        nodeLink.classList.toggle("active");
        nodeLink.parentNode.removeChild(nodeLink.parentNode.querySelector("div.child-containers"));
        return;
    }
    var child_containers = document.createElement("div");
    child_containers.setAttribute("class", "child-containers");

    if (nodeLink.parentNode.data.extra.length) {

        // var ul = document.createElement("ul");
        // ul.setAttribute("class", "extra-content");
        // for (var i = 0; i < nodeLink.parentNode.data.extra.length; i++) {
        //     var extraLi = document.createElement("li");
        //     extraLi.setAttribute("class", "extra-item");
        //     parser = new DOMParser()
        //     extraEl = parser.parseFromString(nodeLink.parentNode.data.extra[i], "text/xml").childNodes[0];
        //     if (extraEl.tagName == "img") {
        //         src = extraEl.getAttribute("src");
        //         var extraEl = document.createElement("img");
        //         extraEl.setAttribute("src", src)
        //         previewButton = document.createElement("div");
        //         previewButton.setAttribute("class", "preview-button");
        //         previewButton.addEventListener('click', showImageFromPreview, false);
        //         previewButton.appendChild(extraEl);
        //         extraEl = previewButton;
        //     }
        //     extraLi.appendChild(extraEl);
        //     ul.appendChild(extraLi);
        // }
        // child_containers.appendChild(ul);
        child_containers.appendChild(createExtraDiv(nodeLink.parentNode.data.extra))
    }

    if (nodeLink.parentNode.data.children.length) {
        var ul = document.createElement("ul");
        ul.setAttribute("class", "child-node-containers");
        for (var i = 0; i < nodeLink.parentNode.data.children.length; i++) {
            ul.appendChild(createNodeHeader(nodeLink.parentNode.data.children[i], !nodeLink.parentNode.odd));
        }
        child_containers.appendChild(ul);
    }

    if (nodeLink.parentNode.data.test_results.length) {
        var ul = document.createElement("ul");
        ul.setAttribute("class", "test-containers");
        for (var i = 0; i < nodeLink.parentNode.data.test_results.length; i++) {
            li = createTestDesc(nodeLink.parentNode.data.test_results[i]);

            ul.appendChild(li)
        }
        child_containers.appendChild(ul);
    }
    nodeLink.parentNode.appendChild(child_containers);
    updateOutcomeCountVisibility()
    updateTestVisibility()

    nodeLink.classList.toggle("active");

};


function prepareResultsHeaders() {
    counts = document.querySelectorAll(".summary-details .summary-result-count")

    for (let c of document.querySelectorAll(".summary-details .count-toggle-button")) {
        c.addEventListener('click', toggleShownState, false);
    }

    document.querySelector("#expand-all-button").addEventListener('click', expandAll, false);
    document.querySelector("#collapse-all-button").addEventListener('click', collapseAll, false);

    var resultsContainer = document.createElement("div");
    resultsContainer.setAttribute("class", "results");
    var resultsContainerUl = document.createElement("ul");
    resultsContainerUl.setAttribute("class", "top-container-list");

    for (var i = 0; i < resultsTree.results.length; i++) {
        resultsContainerUl.appendChild(createNodeHeader(resultsTree.results[i]));
    }
    resultsInfoDiv = document.body.querySelector(".results-info")
    resultsContainer.appendChild(resultsContainerUl)
    resultsInfoDiv.appendChild(resultsContainer)

    updateOutcomeCountVisibility()

}


function createNodeHeader(nodeDetails, odd=false) {

    var summary_container = document.createElement("li");
    summary_container.setAttribute("class", `results-summary-container ${odd ? 'odd' : 'even'}`);
    for (let k of Object.keys(nodeDetails.summary)) {
        if (nodeDetails.summary[k] > 0) {
            summary_container.classList.add(k);
        }
    }
    summary_container.data = nodeDetails
    summary_container.innerHTML = `
        <div class="results-summary-container-header">
            <div class="node-level-description">
                    <div class="name">${nodeDetails.name}</div>
                    <div class="params">${nodeDetails.param_description ? "[" + nodeDetails.param_description + "]" : ""}</div>
            </div>
            <div class="results-summary-numbers-wrapper">
                <div class="node-duration">Duration: ${nodeDetails.duration}s</div>
                <div class="results-summary-numbers">
                    <div class="summary-result-count passed" title="Passes">${nodeDetails.summary.passed}</div>
                    <div class="summary-result-count skipped" title="Skips">${nodeDetails.summary.skipped}</div>
                    <div class="summary-result-count failed" title="Failures">${nodeDetails.summary.failed}</div>
                    <div class="summary-result-count error" title="Errors">${nodeDetails.summary.error}</div>
                    <div class="summary-result-count xfailed" title="Expected failures">${nodeDetails.summary.xfailed}</div>
                    <div class="summary-result-count xpassed" title="Unexpected passes">${nodeDetails.summary.xpassed}</div>
                </div>
            </div>
        </div>
    `
    summary_container.odd = odd
    summary_container.querySelector("div.results-summary-container-header").addEventListener('click', toggleOpenTrigger, false);

    return summary_container
}


function createTestDesc(testDetails) {

    var test_desc = document.createElement("li");
    test_desc.setAttribute("class", `test-result ${testDetails.outcome.toLowerCase()}`);
    test_desc.innerHTML = `
        <div class="result-wrapper">
            <div class="test-info-wrapper">
                <div class="outcome">${testDetails.outcome.toUpperCase()}</div>
                <div class="test-description">
                    <div class="name">${testDetails.name}</div>
                    <div class="params">${testDetails.param_description ? "[" + testDetails.param_description + "]" : ""}</div>
                </div>
                <div class="nodeid tooltip">nodeid<span class="tooltiptext">${testDetails.nodeid}</span></div>
                <div class="location tooltip">location<span class="tooltiptext">${testDetails.location}</span></div>
                <button class="toggle-log"></button>
            </div>
            <div class="duration">Duration: ${testDetails.duration}s</div>
        </div>
        ${testDetails.log}
    `
    test_desc.querySelector("button.toggle-log").addEventListener('click', toggleOpenClass, false);
    return test_desc
}


function expandAll() {
    while (document.querySelectorAll("li.results-summary-container .results-summary-container-header:not(.active)").length > 0) {
        toggleOpen(document.querySelector("li.results-summary-container .results-summary-container-header:not(.active)"));
    }
}

function collapseAll() {
    while (document.querySelectorAll(".top-container-list > li.results-summary-container .results-summary-container-header.active").length > 0) {
        toggleOpen(document.querySelector(".top-container-list > li.results-summary-container .results-summary-container-header.active"));
    }
}


function createExtraDiv(extras) {
    imagesDiv = document.createElement("div");
    imagesDiv.classList.add("extra-image-previews-wrapper");
    imagesDiv.images = [];
    othersDiv = document.createElement("div");
    othersDiv.classList.add("extra-others");

    for (let ex of extras) {
        if (ex.format == "image") {
            imagesDiv.appendChild(createExtraImagePreview(ex));
            // add references for use by slideshow
            imagesDiv.images.push(ex);
        } else {
            switch(ex.format) {
                case "text":
                    othersDiv.appendChild(createExtraText(ex));
                    break;
                case "json":
                    othersDiv.appendChild(createExtraJson(ex));
                    break;
                case "link":
                    othersDiv.appendChild(createExtraLink(ex));
                    break;
                case "html":
                    othersDiv.appendChild(createExtraHtml(ex));
                    break;
                default:
                    break;
            }
        }
    }

    extrasDiv = document.createElement("div");
    extrasDiv.classList.add("extras");
    if (imagesDiv.childNodes.length){
        extrasDiv.appendChild(imagesDiv);
    }
    if (othersDiv.childNodes.length){
        extrasDiv.appendChild(othersDiv);
    }
    extrasDiv.appendChild(othersDiv);
    return extrasDiv
}

function createExtraImagePreview(imageDetails) {
    imagePreviewDiv = document.createElement("div");
    imagePreviewDiv.classList.add("extra");
    imagePreviewDiv.classList.add("extra-image-preview");
    img = document.createElement("img");
    img.setAttribute("src", imageDetails.content);
    img.addEventListener('click', showSlideshow, false);
    imagePreviewDiv.appendChild(img);
    return imagePreviewDiv;
}



function createExtraText(textDetails) {
    textDiv = document.createElement("div");
    textDiv.classList.add("extra");
    textDiv.classList.add("extra-text");
    contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    contentDiv.innerHTML = textDetails.content
    textDiv.appendChild(contentDiv);
    return textDiv;
}

function createExtraJson(jsonDetails) {
    jsonDiv = document.createElement("div");
    jsonDiv.classList.add("extra");
    jsonDiv.classList.add("extra-json");
    contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    contentDiv.innerHTML = JSON.stringify(jsonDetails.content, null, 4);
    jsonDiv.appendChild(contentDiv);
    return jsonDiv;
}

function createExtraLink(linkDetails) {
    linkDiv = document.createElement("div");
    linkDiv.classList.add("extra");
    linkDiv.classList.add("extra-link");
    contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    a = document.createElement("a");
    a.setAttribute("href", linkDetails.content);
    contentDiv.appendChild(a);
    linkDiv.appendChild(contentDiv);
    return linkDiv;
}

function createExtraHtml(htmlDetails) {
    htmlDiv = document.createElement("div");
    htmlDiv.classList.add("extra");
    htmlDiv.classList.add("extra-html");
    contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    contentDiv.innerHTML = htmlDetails.content;
    htmlDiv.appendChild(contentDiv);
    return htmlDiv;
}


function showSlideshow() {
    console.log(this);
}
