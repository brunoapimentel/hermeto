FROM quay.io/bpimente/test-images:cachi2-parent
LABEL maintainer="Red Hat"

WORKDIR /src

COPY . .

RUN pip3 install -r requirements.txt --no-deps --no-cache-dir --require-hashes && \
    pip3 install --no-cache-dir -e . && \
    # the git folder is only needed to determine the package version
    rm -rf .git

RUN cd npm && npm install corepack

ENTRYPOINT ["cachi2"]
