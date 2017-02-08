DOCKER_REVISION ?= testing-$(USER)
DOCKER_TAG = docker-push.ocf.berkeley.edu/slackbridge:$(DOCKER_REVISION)

.PHONY: test
test:
		pre-commit run --all-files

venv: vendor/venv-update requirements.txt requirements-dev.txt
		vendor/venv-update venv= -ppython3 venv install= -r requirements.txt -r requirements-dev.txt

.PHONY: clean
clean:
		rm -rf venv

.PHONY: update-requirements
update-requirements:
		$(eval TMP := $(shell mktemp -d))
		python ./vendor/venv-update venv= $(TMP) -ppython3.4 install= -r requirements.txt
		. $(TMP)/bin/activate && \
				pip install --upgrade pip && \
				pip freeze | sed 's/^ocflib==.*/ocflib/' > requirements.txt
		rm -rf $(TMP)

.PHONY: cook-image
cook-image:
		docker build -t $(DOCKER_TAG) .

.PHONY: push-image
push-image:
		docker push $(DOCKER_TAG)
