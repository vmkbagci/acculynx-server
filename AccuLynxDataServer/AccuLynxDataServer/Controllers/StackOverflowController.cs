using Microsoft.AspNetCore.Mvc;
using StackOverflowLibrary;
using StackOverflowLibrary.Entities;

namespace AccuLynxDataServer.Controllers
{
    [ApiController]
    [Route("[controller]")]
    public class StackOverflowController : ControllerBase
    {
        private readonly ILogger<StackOverflowController> _logger;

        public StackOverflowController(ILogger<StackOverflowController> logger)
        {
            _logger = logger;
        }

        [HttpGet(Name = "GetRandomQuestion")]
        public async Task<Question> GetRandomQuestion(DateTime createdAtOrAfter)
        {
            var stackOverflowAccessor = new StackOverflowAccessor();

            var questionIds = await stackOverflowAccessor.GetQuestionIdsWithAnswers(createdAtOrAfter);

            if (!questionIds.Any()) return null;

            var queriedIndexes = new List<int>();

            while (queriedIndexes.Count < questionIds.Count)
            {
                var randomIdIndex = new Random().Next(questionIds.Count);

                if (queriedIndexes.Contains(randomIdIndex)) { continue; } // We don't want to query the answers for the same Id again

                queriedIndexes.Add(randomIdIndex);

                var randomQuestion = await stackOverflowAccessor.GetQuestionById(questionIds[randomIdIndex]);

                if (randomQuestion.Answers.Any(ans => ans.IsAccepted)) return randomQuestion;
            }

            return null;
        }
    }
}
